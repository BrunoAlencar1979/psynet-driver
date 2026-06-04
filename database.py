import os
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.ext.declarative import declarative_base

# Pega a URL do banco das variáveis de ambiente do Render (Segurança máxima!)
DATABASE_URL = os.environ.get("DATABASE_URL")

# Proteção: Se a variável não for encontrada, o servidor avisa no log
if not DATABASE_URL:
    raise ValueError("A variável de ambiente DATABASE_URL não está configurada no servidor!")

engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
