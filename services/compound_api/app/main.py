from fastapi import FastAPI
app = FastAPI(title='Compound API')


@app.get('/compound/health')
def compound_health() -> dict[str, bool]:
    return {'ok': True}
