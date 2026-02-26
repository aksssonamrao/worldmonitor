try:
    from fastapi import FastAPI
except ModuleNotFoundError:  # pragma: no cover - local fallback for offline test environments
    class FastAPI:  # type: ignore[override]
        def __init__(self, title: str) -> None:
            self.title = title

        def get(self, _path: str):
            def decorator(func):
                return func

            return decorator


app = FastAPI(title='Compound API')


@app.get('/compound/health')
def compound_health() -> dict[str, bool]:
    return {'ok': True}
