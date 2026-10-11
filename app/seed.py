import argparse
import json

from app.services.bootstrap import find_excel, reset_and_import


def main():
    parser = argparse.ArgumentParser(description="重建数据库并导入集换社 Excel")
    parser.add_argument("excel", nargs="?", help="xlsx 路径，默认使用上级目录的汇总表")
    args = parser.parse_args()
    path = None
    if args.excel:
        from pathlib import Path

        path = Path(args.excel)
    elif find_excel() is None:
        raise SystemExit("找不到 Excel")
    summary = reset_and_import(path)
    print(json.dumps({"success": summary["success"], "failed": summary["failed"], "skipped": summary["skipped"], "sheets": [
        {"sheet": item["sheet"], "card_code": item.get("card_code"), "success": item["success"], "failed": item["failed"], "skipped": item["skipped"]}
        for item in summary["sheets"]
    ]}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
