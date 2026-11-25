"""Public Kick acquisition via the maintained yt-dlp extractor; no heatmap is assumed."""
from .providers import YtDlpSource


class KickSource(YtDlpSource):
    def __init__(self, url):
        super().__init__(url, "kick")

    def options(self, metadata=False):
        try:
            import curl_cffi
        except ImportError as error:
            raise ValueError("O suporte Kick exige Setup-Kick.ps1.") from error
        return super().options(metadata)
