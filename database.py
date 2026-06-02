import os
from sqlalchemy import create_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker

# A URL virá de uma variável de ambiente (vamos configurar isso no Render)
SQLALCHEMY_DATABASE_URL = os.getenv("DATABASE_URL")

engine = create_engine("postgresql://neondb_owner:npg_nTfWscgFY5x4@ep-blue-poetry-acwknpga-pooler.sa-east-1.aws.neon.tech/neondb?sslmode=require&channel_binding=require")
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()