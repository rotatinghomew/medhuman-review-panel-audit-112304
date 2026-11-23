"""读取教务交换包并检查文件结构。"""
import argparse
import csv
import json
from pathlib import Path


def inspect_bundle(root, manifest):
    """读取清单描述的表并返回名称与记录数。"""
    counts = {}
    for filename, fields in manifest.items():
        with (root / filename).open(encoding="utf-8", newline="") as source:
            reader = csv.reader(source, strict=True)
            if next(reader, None) != fields:
                raise ValueError(f"{filename} 的表头与资料清单不符")
            count = 0
            for line, row in enumerate(reader, start=2):
                if len(row) != len(fields):
                    raise ValueError(f"{filename} 第 {line} 行的字段数量不符")
                count += 1
            counts[filename] = count
    return counts


def main():
    """从终端打开资料包，显示各表记录数。"""
    parser = argparse.ArgumentParser(description="检查合成资料交换包")
    parser.add_argument("bundle", type=Path, help="含清单及数据表的目录")
    args = parser.parse_args()
    try:
        manifest = json.loads((args.bundle / "manifest.json").read_text(encoding="utf-8"))
        counts = inspect_bundle(args.bundle, manifest)
    except (OSError, ValueError) as error:
        parser.exit(2, f"资料读取失败：{error}\n")
    print(json.dumps(counts, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
