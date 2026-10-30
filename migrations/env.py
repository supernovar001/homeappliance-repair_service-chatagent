"""Alembic 실행 환경. 테스트는 config.attributes["connection"]으로 연결을 넘깁니다."""
from logging.config import fileConfig

from alembic import context
from sqlalchemy import create_engine

from backend.models import Base
from backend.settings import settings

config = context.config
if config.config_file_name:
    fileConfig(config.config_file_name)


def run(connection):
    context.configure(connection=connection, target_metadata=Base.metadata, compare_type=True)
    with context.begin_transaction():
        context.run_migrations()


connection = config.attributes.get("connection")
if connection is not None:
    run(connection)
else:
    with create_engine(config.get_main_option("sqlalchemy.url") or settings.database_url).connect() as conn:
        run(conn)
