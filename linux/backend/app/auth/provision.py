"""Create an officer through the local administrative shell, never anonymous HTTP.

Run: python -m app.auth.provision --badge-number 038291 --name 张伟 --unit 刑侦 --admin
The password is prompted twice and is never accepted on the command line.
The database must have been upgraded with Alembic first.
"""
import argparse
import getpass
import os

from sqlalchemy import inspect

from app.database.session import make_engine, make_session_factory
from app.services.officer_service import OfficerService


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description='配置民警账号（密码通过隐藏提示输入）')
    parser.add_argument('--badge-number', required=True)
    parser.add_argument('--name', required=True)
    parser.add_argument('--unit', default='')
    parser.add_argument('--admin', action='store_true')
    args = parser.parse_args(argv)
    url = os.getenv('DATABASE_URL')
    if not url and os.getenv('SUSPECT_DB_PATH'):
        url = 'sqlite:///' + os.path.abspath(os.environ['SUSPECT_DB_PATH'])
    engine = make_engine(url)
    if 'officers' not in inspect(engine).get_table_names():
        parser.error('请先执行 alembic upgrade head；此命令不会代替数据库迁移')
    first = getpass.getpass('密码（至少12字符）: ')
    second = getpass.getpass('再次输入密码: ')
    if first != second:
        parser.error('两次密码不一致')
    with make_session_factory(engine)() as db:
        result = OfficerService(db).provision_officer(badge_number=args.badge_number, name=args.name,
                    unit=args.unit, password=first, is_admin=args.admin)
        db.commit()
    print(f"已创建账号 {result['displayName']}；未显示或保存明文密码")
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
