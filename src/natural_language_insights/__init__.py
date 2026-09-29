def main() -> None:
    import uvicorn

    from natural_language_insights.config.settings import settings

    uvicorn.run("natural_language_insights.main:app", host=settings.host, port=settings.port)
