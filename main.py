import time
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from database.connection import engine, Base
from routers import auth, chat, history


Base.metadata.create_all(bind=engine)

origins = [
    "http://localhost:3000", # Port Vite React của m
    "http://127.0.0.1:3000",
]

app = FastAPI(title="Hà Nội Travel & Food RAG API", version="2.0.0")

# 1. MIDDLEWARE
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.middleware("http")
async def add_process_time_header(request, call_next):
    start_time = time.time()
    response = await call_next(request)
    duration = time.time() - start_time
    response.headers["X-Process-Time"] = f"{duration:.4f}s"
    return response

# 2. REGISTER ROUTERS
app.include_router(auth.router, prefix="/api")
app.include_router(chat.router, prefix="/api")
app.include_router(history.router, prefix="/api")
@app.get("/")
def root():
    return {"message": "Chào mừng đến với Hà Nội Travel & Food RAG API!"}