# main.py — 统一入口：回测 / 下载数据
import sys
import io
if sys.platform == 'win32':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

import argparse
from run import main, load_config, download_all, download_spy_only


def cli():
    parser = argparse.ArgumentParser(description='回测或下载数据')
    parser.add_argument('--download', action='store_true', help='下载 S&P 500 全量数据（使用 config 中的日期与目录）')
    parser.add_argument('--download-spy', action='store_true', help='仅下载 SPY（使用 config 中的日期与目录）')
    args = parser.parse_args()
    if args.download:
        config = load_config()
        download_all(config)
    elif args.download_spy:
        config = load_config()
        download_spy_only(config)
    else:
        main()


if __name__ == '__main__':
    cli()
