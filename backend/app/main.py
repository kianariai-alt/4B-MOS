from fastapi import FastAPI

app = FastAPI(
    title="4B-MOS",
    description="4B Medical Operating System",
    version="0.1.0",
    docs_url="/docs",
    redoc_url="/redoc",
)


@app.get("/")
async def root():
    return {
        "application": "4B-MOS",
        "name": "4B Medical Operating System",
        "version": "0.1.0",
        "status": "running",
    }


@app.get("/health")
async def health():
    return {
        "status": "healthy",
        "service": "4B-MOS Backend",
    }