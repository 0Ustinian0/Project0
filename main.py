# main.py
import sys
import io
if sys.platform == 'win32':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

import argparse
from run import main, load_config, download_all, download_spy_only, download_fundamentals


def cli():
    parser = argparse.ArgumentParser(description='回测或下载数据')
    parser.add_argument('--download', action='store_true', help='下载 S&P 500 全量数据（使用 config 中的日期与目录）')
    parser.add_argument('--download-spy', action='store_true', help='仅下载 SPY（使用 config 中的日期与目录）')
    parser.add_argument('--download-fundamentals', action='store_true', dest='download_fundamentals',
                        help='拉取基本面（yfinance）并保存为 data_dir/fundamentals.csv')
    parser.add_argument('--optimize', action='store_true', help='参数优化：使用 config 中 optimization（默认 grid）')
    parser.add_argument('--optimize-wfa', action='store_true', dest='optimize_wfa',
                        help='参数优化：Walk-Forward 向前步进（覆盖 config 中 method）')
    parser.add_argument('--optimize-bayesian', action='store_true', dest='optimize_bayesian',
                        help='参数优化：贝叶斯优化（需 scikit-optimize，覆盖 config 中 method）')
    parser.add_argument('--multi-strategy', action='store_true', dest='multi_strategy',
                        help='多策略并行：按权重分配资金运行后合并收益曲线（使用 config 中 multi_strategy）')
    args = parser.parse_args()
    if args.download:
        config = load_config()
        download_all(config)
    elif args.download_spy:
        config = load_config()
        download_spy_only(config)
    elif args.download_fundamentals:
        config = load_config()
        download_fundamentals(config)
    else:
        force_opt = args.optimize or args.optimize_wfa or args.optimize_bayesian
        method = 'walk_forward' if args.optimize_wfa else ('bayesian' if args.optimize_bayesian else None)
        main(force_optimize=force_opt, force_multi_strategy=args.multi_strategy, optimize_method=method)


if __name__ == '__main__':
    cli()
