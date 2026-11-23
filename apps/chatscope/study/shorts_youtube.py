"""OAuth and resumable private uploads for the review queue."""

import re
from urllib.parse import urlsplit


SCOPES = [
    "https://www.googleapis.com/auth/youtube.upload",
    "https://www.googleapis.com/auth/youtube.readonly",
]
EDIT_SCOPE = "https://www.googleapis.com/auth/youtube.force-ssl"
API = "https://www.googleapis.com/youtube/v3/"
UPLOAD = "https://www.googleapis.com/upload/youtube/v3/videos"
CHUNK = 4 * 1024 * 1024


class UploadError(Exception):
    """A message safe for local logs."""


def checked(response, allowed=(200,)):
    if response.status_code not in allowed:
        try:
            error = response.json().get("error", {})
            reasons = [entry.get("reason", "") for part in ("errors", "details")
                       for entry in error.get(part, []) if isinstance(entry, dict)]
        except (AttributeError, ValueError):
            reasons = []
        if set(reasons) & {"accessNotConfigured", "SERVICE_DISABLED"}:
            raise UploadError("A YouTube Data API v3 está desativada no projeto Google Cloud.")
        if set(reasons) & {"insufficientPermissions", "ACCESS_TOKEN_SCOPE_INSUFFICIENT"}:
            raise UploadError("A autorização Google não permite esta operação no YouTube.")
        codes = [reason for reason in reasons if re.fullmatch(r"[A-Za-z0-9_]{1,80}", reason)]
        detail = f" ({', '.join(dict.fromkeys(codes))})" if codes else ""
        raise UploadError(f"YouTube devolveu HTTP {response.status_code}{detail}.")
    return response


def upload_url(url):
    parts = urlsplit(url)
    if parts.scheme != "https" or parts.netloc != "www.googleapis.com" or parts.path != "/upload/youtube/v3/videos":
        raise UploadError("O YouTube devolveu um endereço de upload inesperado.")
    return url


def connect(client_file, account=None):
    from google_auth_oauthlib.flow import InstalledAppFlow, WSGITimeoutError

    flow = InstalledAppFlow.from_client_secrets_file(
        str(client_file), scopes=[EDIT_SCOPE], autogenerate_code_verifier=True,
    )
    options = {"login_hint": account} if account else {}
    try:
        return flow.run_local_server(
            host="127.0.0.1", port=0, open_browser=False, access_type="offline",
            prompt="consent", timeout_seconds=600,
            authorization_prompt_message="Abre este endereço para autorizar o canal de revisão:\n{url}",
            success_message="Autorização recebida. Volta ao terminal.",
            **options,
        )
    except WSGITimeoutError as error:
        raise UploadError("O Google não devolveu a autorização a tempo.") from error


def authorized_session(credentials):
    from google.auth.transport.requests import AuthorizedSession

    return AuthorizedSession(credentials)


def selected_channel(session):
    result = checked(session.get(
        API + "channels", params={"part": "id,snippet", "mine": "true"},
        timeout=20, allow_redirects=False,
    )).json()
    channels = result.get("items", [])
    if len(channels) != 1 or result.get("nextPageToken"):
        raise UploadError("O YouTube tem de devolver um único canal. Cria ou seleciona o canal de revisão.")
    return channels[0]["id"], channels[0]["snippet"]["title"]


def verify_channel(session, expected):
    channel_id, name = selected_channel(session)
    if channel_id != expected:
        raise UploadError("A conta autorizada não corresponde ao ID do canal de revisão.")
    return name


def begin_upload(session, size, title, description, made_for_kids):
    response = checked(session.post(
        UPLOAD, params={"uploadType": "resumable", "part": "snippet,status"},
        headers={"X-Upload-Content-Length": str(size), "X-Upload-Content-Type": "video/mp4"},
        json={
            "snippet": {"title": title, "description": description, "categoryId": "20"},
            "status": {"privacyStatus": "private", "selfDeclaredMadeForKids": made_for_kids},
        },
        timeout=20, allow_redirects=False,
    ), (200, 201))
    return upload_url(response.headers.get("Location", ""))


def committed(response, size):
    value = response.headers.get("Range", "")
    if not value:
        return 0
    match = re.fullmatch(r"bytes=0-(\d+)", value)
    if not match or int(match[1]) >= size:
        raise UploadError("O YouTube devolveu uma posição de upload inválida.")
    return int(match[1]) + 1


def send_media(session, url, file, size):
    url = upload_url(url)
    response = session.put(
        url, data=b"", headers={"Content-Length": "0", "Content-Range": f"bytes */{size}"},
        timeout=30, allow_redirects=False,
    )
    if response.status_code in (404, 410):
        raise UploadError("A sessão de upload expirou. Confirma o vídeo no Studio antes de repetir.")
    checked(response, (200, 201, 308))
    while response.status_code == 308:
        start = committed(response, size)
        file.seek(start)
        data = file.read(CHUNK)
        if not data:
            raise UploadError("O ficheiro preparado terminou antes do esperado.")
        end = start + len(data) - 1
        response = checked(session.put(
            url, data=data,
            headers={
                "Content-Type": "video/mp4",
                "Content-Range": f"bytes {start}-{end}/{size}",
            },
            timeout=60, allow_redirects=False,
        ), (200, 201, 308))
        if response.status_code == 308 and committed(response, size) <= start:
            raise UploadError("O upload não avançou. A próxima tentativa retoma a sessão.")
    video_id = response.json().get("id", "")
    if not re.fullmatch(r"[A-Za-z0-9_-]{11}", video_id):
        raise UploadError("O YouTube não confirmou o ID do vídeo.")
    return video_id


def lookup_video(session, video_id):
    videos = checked(session.get(
        API + "videos", params={"part": "snippet,status", "id": video_id},
        timeout=20, allow_redirects=False,
    )).json().get("items", [])
    return videos[0] if videos else None


def video_status(session, video_id, channel_id):
    video = lookup_video(session, video_id)
    if video is None:
        return False
    status = video["status"]
    if video["snippet"]["channelId"] != channel_id or status["privacyStatus"] != "private":
        raise UploadError("O vídeo não está privado no canal de revisão esperado.")
    if status["uploadStatus"] in ("deleted", "failed", "rejected"):
        raise UploadError(f"O YouTube devolveu o estado {status['uploadStatus']} para o vídeo.")
    return status["uploadStatus"] == "processed"


def update_title(session, video_id, channel_id, title, *, allow_public=False):
    video = lookup_video(session, video_id)
    if video is None:
        raise UploadError("O YouTube ainda não devolveu o vídeo para editar.")
    snippet = video["snippet"]
    visibility = video["status"]["privacyStatus"]
    if snippet["channelId"] != channel_id or (visibility != "private" and not (allow_public and visibility == "public")):
        raise UploadError("O canal ou a visibilidade do vídeo não correspondem à edição pedida.")
    if snippet["title"] == title:
        return
    fields = ("title", "categoryId", "description", "tags", "defaultLanguage")
    metadata = {name: snippet[name] for name in fields if name in snippet}
    metadata["title"] = title
    result = checked(session.put(
        API + "videos", params={"part": "snippet"},
        json={"id": video_id, "snippet": metadata},
        timeout=20, allow_redirects=False,
    )).json()
    if result.get("snippet", {}).get("title") != title:
        raise UploadError("O YouTube não confirmou o novo título.")


def publish_video(session, video, channel_id):
    status = video["status"]
    if video["snippet"]["channelId"] != channel_id or status["uploadStatus"] != "processed":
        raise UploadError("O vídeo precisa de estar processado no canal de revisão.")
    if status["privacyStatus"] == "public":
        return
    if status["privacyStatus"] != "private":
        raise UploadError("Visibilidade inesperada antes de publicar.")
    fields = ("embeddable", "license", "publicStatsViewable", "selfDeclaredMadeForKids", "containsSyntheticMedia")
    changes = {name: status[name] for name in fields if name in status}
    changes["privacyStatus"] = "public"
    result = checked(session.put(
        API + "videos", params={"part": "status"},
        json={"id": video["id"], "status": changes},
        timeout=20, allow_redirects=False,
    )).json()
    if result.get("status", {}).get("privacyStatus") != "public":
        raise UploadError("O YouTube não confirmou a publicação.")
