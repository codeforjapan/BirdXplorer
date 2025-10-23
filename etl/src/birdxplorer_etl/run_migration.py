#!/usr/bin/env python3
"""
データベースマイグレーション実行スクリプト
ECS Taskから呼び出され、Alembicマイグレーションを実行する
"""
import os
import sys
import logging
from pathlib import Path

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def setup_environment():
    """環境変数を設定"""
    # DB接続情報を環境変数から取得してBX_STORAGE_SETTINGS形式に変換
    db_host = os.environ.get('DB_HOST')
    db_port = os.environ.get('DB_PORT', '5432')
    db_name = os.environ.get('DB_NAME', 'postgres')
    db_user = os.environ.get('DB_USER')
    db_pass = os.environ.get('DB_PASS')
    
    if not all([db_host, db_user, db_pass]):
        logger.error("Required environment variables are missing")
        logger.error(f"DB_HOST: {db_host}, DB_USER: {db_user}, DB_PASS: {'***' if db_pass else None}")
        return False
    
    # birdxplorer_commonが期待する環境変数形式に設定
    os.environ['BX_STORAGE_SETTINGS__HOST'] = db_host
    os.environ['BX_STORAGE_SETTINGS__PORT'] = db_port
    os.environ['BX_STORAGE_SETTINGS__DATABASE'] = db_name
    os.environ['BX_STORAGE_SETTINGS__USERNAME'] = db_user
    os.environ['BX_STORAGE_SETTINGS__PASSWORD'] = db_pass
    
    logger.info(f"Database connection configured: {db_user}@{db_host}:{db_port}/{db_name}")
    return True


def run_migration():
    """Alembicマイグレーションを実行"""
    try:
        # 環境変数の設定
        if not setup_environment():
            logger.error("Failed to setup environment")
            return 1
        
        # Alembicのインポート（環境変数設定後）
        from alembic import command
        from alembic.config import Config
        
        # マイグレーションディレクトリのパスを特定
        # /app/migrate/alembic.ini を想定
        migration_dir = Path('/app/migrate')
        alembic_ini_path = migration_dir / 'alembic.ini'
        
        if not alembic_ini_path.exists():
            logger.error(f"Alembic config file not found: {alembic_ini_path}")
            logger.info("Trying alternative path...")
            
            # 代替パス: プロジェクトルートからの相対パス
            current_dir = Path(__file__).parent.parent.parent.parent
            migration_dir = current_dir / 'migrate'
            alembic_ini_path = migration_dir / 'alembic.ini'
            
            if not alembic_ini_path.exists():
                logger.error(f"Alembic config file not found at alternative path: {alembic_ini_path}")
                return 1
        
        logger.info(f"Using Alembic config: {alembic_ini_path}")
        
        # Alembic設定を読み込み
        alembic_cfg = Config(str(alembic_ini_path))
        
        # スクリプトの場所を設定
        script_location = migration_dir / 'migration'
        alembic_cfg.set_main_option('script_location', str(script_location))
        
        logger.info(f"Migration script location: {script_location}")
        logger.info("Starting database migration...")
        
        # 現在のマイグレーションバージョンを確認
        try:
            from alembic.script import ScriptDirectory
            from alembic.runtime.migration import MigrationContext
            from birdxplorer_common.storage import gen_storage
            from birdxplorer_common.settings import GlobalSettings
            
            settings = GlobalSettings()
            storage = gen_storage(settings=settings)
            
            with storage.engine.connect() as connection:
                context = MigrationContext.configure(connection)
                current_rev = context.get_current_revision()
                logger.info(f"Current database revision: {current_rev or 'None (empty database)'}")
            
            script = ScriptDirectory.from_config(alembic_cfg)
            head_rev = script.get_current_head()
            logger.info(f"Target revision (head): {head_rev}")
            
            if current_rev == head_rev:
                logger.info("Database is already up to date. No migration needed.")
                return 0
                
        except Exception as e:
            logger.warning(f"Could not check current revision: {e}")
            logger.info("Proceeding with migration anyway...")
        
        # マイグレーションを最新バージョンまで実行
        command.upgrade(alembic_cfg, 'head')
        
        logger.info("✅ Migration completed successfully")
        return 0
        
    except Exception as e:
        logger.error(f"❌ Migration failed: {str(e)}", exc_info=True)
        return 1


if __name__ == '__main__':
    exit_code = run_migration()
    sys.exit(exit_code)