"""
参数优化：网格搜索 (Grid Search) 与向前步进分析 (Walk-Forward Analysis)。
提供多种最终参数选择策略：best / plateau / plateau_kde / cluster / robust。
"""
import itertools
import logging
from collections import Counter, defaultdict

import backtrader as bt

from data.manager import load_data_into_cerebro
from utils.logger import Logger


def _closest_in_list(value, candidates):
    """在候选列表中找到最接近 value 的项（用于数值型参数取整到网格）。"""
    if not candidates:
        return value
    try:
        return min(candidates, key=lambda c: abs(float(c) - float(value)))
    except (TypeError, ValueError):
        return candidates[0]


def _params_match(p1, p2):
    """两组参数是否等价（数值容差、类型 int/float 一致）。"""
    if set(p1.keys()) != set(p2.keys()):
        return False
    for k in p1:
        a, b = p1[k], p2[k]
        if isinstance(a, (int, float)) and isinstance(b, (int, float)):
            if abs(float(a) - float(b)) > 1e-9:
                return False
        elif a != b:
            return False
    return True


def _params_in_results(params, all_results):
    """params 是否在 all_results 的某一条中出现（精确或匹配）。"""
    for p, _ in all_results:
        if _params_match(params, p):
            return True
    return False


def _snap_params_to_grid(params, grid_candidates):
    """将参数字典中每个值落到最近网格点。"""
    out = {}
    for k, v in params.items():
        if k in grid_candidates and grid_candidates[k]:
            out[k] = _closest_in_list(v, grid_candidates[k])
            if all(isinstance(x, int) for x in grid_candidates[k]):
                out[k] = int(out[k])
        else:
            out[k] = v
    return out


def _grid_param_index(value, grid_list):
    """value 在 grid_list 中的下标；若不在则返回最接近的下标；空列表返回 0。"""
    if not grid_list:
        return 0
    try:
        for i, c in enumerate(grid_list):
            if abs(float(c) - float(value)) < 1e-9:
                return i
        idx = min(range(len(grid_list)), key=lambda i: abs(float(grid_list[i]) - float(value)))
        return idx
    except (TypeError, ValueError):
        return 0


def _grid_neighbor_indices(params_dict, all_results, grid_candidates, radius=1):
    """在网格空间内与 params_dict 距离不超过 radius（曼哈顿步数）的结果下标集合。"""
    grid_keys = [k for k in params_dict if k in grid_candidates and grid_candidates[k]]
    if not grid_keys:
        return list(range(len(all_results)))
    ref_indices = {}
    for k in grid_keys:
        ref_indices[k] = _grid_param_index(params_dict[k], grid_candidates[k])
    neighbors = []
    for idx, (p, _) in enumerate(all_results):
        dist = 0
        for k in grid_keys:
            idx_p = _grid_param_index(p.get(k, 0), grid_candidates[k])
            dist += abs(idx_p - ref_indices[k])
        if dist <= radius * len(grid_keys):  # 每维最多差 radius
            neighbors.append(idx)
    return neighbors


def compute_robustness_score(result_idx, all_results, grid_candidates, metric_idx=1, radius=1):
    """
    计算某条结果的局部稳健性：其网格邻域内表现的均值/标准差（高且稳则得分高）。
    metric_idx: all_results 元组中指标所在位置，通常为 1。
    """
    if result_idx < 0 or result_idx >= len(all_results):
        return 0.0
    params = all_results[result_idx][0]
    neighbor_idxs = _grid_neighbor_indices(params, all_results, grid_candidates, radius=radius)
    if not neighbor_idxs:
        return 0.0
    values = []
    for i in neighbor_idxs:
        v = all_results[i][metric_idx]
        if v is not None:
            try:
                values.append(float(v))
            except (TypeError, ValueError):
                pass
    if not values:
        return 0.0
    import statistics
    mean_v = sum(values) / len(values)
    std_v = (sum((x - mean_v) ** 2 for x in values) / len(values)) ** 0.5
    if std_v < 1e-9:
        return mean_v * 1e6
    return mean_v / (std_v + 1e-9)


def _build_grid_candidates(param_keys, all_results, grid_candidates_from_flow):
    """统一得到 grid_candidates。"""
    if grid_candidates_from_flow:
        return grid_candidates_from_flow
    grid_candidates = {}
    for k in param_keys:
        vals = set()
        for params, _ in all_results:
            if k in params:
                v = params[k]
                try:
                    vals.add(float(v) if not isinstance(v, bool) else v)
                except (TypeError, ValueError):
                    vals.add(v)
        grid_candidates[k] = sorted(vals) if vals and all(isinstance(x, (int, float)) for x in vals) else list(vals)
    return grid_candidates


def _get_top_runs_by_pct_or_threshold(all_results, top_pct=0.2, plateau_threshold=None, maximize=True):
    """
    取「优秀组合」：按排名前 top_pct，或按指标阈值（metric >= threshold / <= threshold）。
    返回子列表，保证至少 1 条。
    """
    if plateau_threshold is not None:
        if maximize:
            top_runs = [r for r in all_results if r[1] is not None and r[1] >= plateau_threshold]
        else:
            top_runs = [r for r in all_results if r[1] is not None and r[1] <= plateau_threshold]
        return top_runs if top_runs else all_results[: max(1, int(len(all_results) * top_pct))]
    n = max(1, int(len(all_results) * top_pct))
    return all_results[:n]


def select_final_params(all_results, method='best', top_pct=0.2, maximize=True, grid_candidates=None,
                        robust_alpha=0.7, robust_radius=1, n_clusters=3, plateau_threshold=None):
    """
    从网格搜索结果中确定「最终参数」。
    all_results: [(params_dict, metric_value), ...]，已按 metric 排序（最优在前）。
    method:
      - best: 单点最优（可能过拟合）。
      - plateau: 参数高地——取 top_pct 组合，各参数中位数落回网格。
      - plateau_freq: 改进 Plateau——取 top_pct 或按 plateau_threshold 筛选优秀组合，各参数取出现频率最高的值，落回网格。
      - plateau_kde: 取 top_pct 组合，各参数用 KDE 取密度峰值（众数）落回网格；若组合不在结果中则取最近有效组合。
      - cluster: 对 top_pct 组合做 KMeans 聚类，在最大簇内取中位数落回网格（保持参数相关性区域）。
      - robust: 对每条结果算局部稳健性得分，综合得分 = alpha*性能排名 + (1-alpha)*稳健性排名，取综合最高。
    top_pct: plateau / plateau_freq / plateau_kde / cluster 时取前多少比例（未设阈值时）。
    plateau_threshold: 若设置，则用「指标 >= 该值」（maximize）或「<= 该值」筛选优秀组合，替代 top_pct。
    grid_candidates: {param_name: [grid_value, ...]}，落回网格用。
    robust_alpha: robust 时性能排名权重（0~1），稳健性排名权重为 1-alpha。
    robust_radius: robust 时邻域半径（网格步数）。
    n_clusters: cluster 时聚类数。
    返回: (final_params_dict, chosen_metric_value 或 None)
    """
    if not all_results:
        return {}, None

    if method == 'best':
        return all_results[0][0].copy(), all_results[0][1]

    param_keys = list(all_results[0][0].keys()) if all_results else []
    grid_candidates = _build_grid_candidates(param_keys, all_results, grid_candidates)
    top_runs = _get_top_runs_by_pct_or_threshold(all_results, top_pct, plateau_threshold, maximize)

    # ---------- plateau（原逻辑） ----------
    if method == 'plateau':
        final = {}
        for k in param_keys:
            values = [p[k] for p, _ in top_runs if k in p]
            if not values:
                final[k] = top_runs[0][0].get(k)
                continue
            if all(isinstance(x, bool) for x in values):
                final[k] = Counter(values).most_common(1)[0][0]
                continue
            try:
                numeric = [float(x) for x in values if isinstance(x, (int, float))]
                if numeric:
                    median_val = sorted(numeric)[len(numeric) // 2]
                    if k in grid_candidates and grid_candidates[k]:
                        v = _closest_in_list(median_val, grid_candidates[k])
                        final[k] = int(v) if all(isinstance(x, int) for x in grid_candidates[k]) else v
                    else:
                        final[k] = int(median_val) if all(isinstance(x, int) for x in values) else median_val
                else:
                    final[k] = Counter(values).most_common(1)[0][0]
            except (TypeError, ValueError):
                final[k] = values[0]
        chosen_value = next((val for p, val in all_results if _params_match(p, final)), all_results[0][1])
        return final, chosen_value

    # ---------- plateau_freq：优秀组合中每参数取频率最高的值，落回网格 ----------
    if method == 'plateau_freq':
        final = {}
        for k in param_keys:
            values = [p[k] for p, _ in top_runs if k in p]
            if not values:
                final[k] = top_runs[0][0].get(k)
                continue
            # 频率分布，取出现频率最高的值（众数）
            cnt = Counter(values)
            mode_value = cnt.most_common(1)[0][0]
            if k in grid_candidates and grid_candidates[k]:
                # 若不在网格上则取离它最近的网格值
                if mode_value not in grid_candidates[k]:
                    try:
                        v = _closest_in_list(float(mode_value) if isinstance(mode_value, (int, float)) else mode_value, grid_candidates[k])
                        final[k] = int(v) if all(isinstance(x, int) for x in grid_candidates[k]) else v
                    except (TypeError, ValueError):
                        final[k] = mode_value
                else:
                    final[k] = mode_value
            else:
                final[k] = mode_value
        final = _snap_params_to_grid(final, grid_candidates)
        if not _params_in_results(final, all_results):
            grid_keys = [k for k in param_keys if k in grid_candidates and grid_candidates[k]]
            best_idx = 0
            best_dist = float('inf')
            for idx, (p, _) in enumerate(all_results):
                d = sum(abs(_grid_param_index(final.get(k), grid_candidates[k]) - _grid_param_index(p.get(k), grid_candidates[k])) for k in grid_keys)
                if d < best_dist:
                    best_dist = d
                    best_idx = idx
            final = all_results[best_idx][0].copy()
        chosen_value = next((val for p, val in all_results if _params_match(p, final)), all_results[0][1])
        return final, chosen_value

    # ---------- plateau_kde：KDE 密度峰值落回网格 ----------
    if method == 'plateau_kde':
        final = {}
        for k in param_keys:
            values = [p[k] for p, _ in top_runs if k in p]
            if not values:
                final[k] = top_runs[0][0].get(k)
                continue
            if all(isinstance(x, bool) for x in values):
                final[k] = Counter(values).most_common(1)[0][0]
                continue
            try:
                numeric = [float(x) for x in values if isinstance(x, (int, float))]
                if numeric and len(numeric) >= 2:
                    try:
                        from scipy.stats import gaussian_kde
                        kde = gaussian_kde(numeric)
                        grid_vals = grid_candidates.get(k)
                        if grid_vals:
                            x = [float(v) for v in grid_vals]
                            dens = kde(x)
                            mode_value = x[dens.argmax()]
                            v = _closest_in_list(mode_value, grid_vals)
                            final[k] = int(v) if all(isinstance(g, int) for g in grid_vals) else v
                        else:
                            final[k] = int(sorted(numeric)[len(numeric) // 2])
                    except ImportError:
                        median_val = sorted(numeric)[len(numeric) // 2]
                        if k in grid_candidates and grid_candidates[k]:
                            v = _closest_in_list(median_val, grid_candidates[k])
                            final[k] = int(v) if all(isinstance(x, int) for x in grid_candidates[k]) else v
                        else:
                            final[k] = int(median_val) if all(isinstance(x, int) for x in values) else median_val
                elif numeric:
                    final[k] = _closest_in_list(numeric[0], grid_candidates.get(k, numeric))
                else:
                    final[k] = Counter(values).most_common(1)[0][0]
            except (TypeError, ValueError):
                final[k] = values[0]
        final = _snap_params_to_grid(final, grid_candidates)
        if not _params_in_results(final, all_results):
            # 找网格距离最近的一条有效组合（曼哈顿步数）
            best_idx = 0
            best_dist = float('inf')
            grid_keys = [k for k in param_keys if k in grid_candidates and grid_candidates[k]]
            for idx, (p, _) in enumerate(all_results):
                d = sum(abs(_grid_param_index(final.get(k), grid_candidates[k]) - _grid_param_index(p.get(k), grid_candidates[k])) for k in grid_keys)
                if d < best_dist:
                    best_dist = d
                    best_idx = idx
            final = all_results[best_idx][0].copy()
        chosen_value = next((val for p, val in all_results if _params_match(p, final)), all_results[0][1])
        return final, chosen_value

    # ---------- cluster：KMeans 最大簇中位数 ----------
    if method == 'cluster':
        try:
            from sklearn.cluster import KMeans
            from sklearn.preprocessing import StandardScaler
        except ImportError:
            return select_final_params(all_results, method='plateau', top_pct=top_pct, maximize=maximize,
                                      grid_candidates=grid_candidates)
        # 只对网格参数做聚类
        grid_keys = [k for k in param_keys if k in grid_candidates and grid_candidates[k] and
                     all(isinstance(x, (int, float)) for x in grid_candidates[k])]
        if not grid_keys:
            return select_final_params(all_results, method='plateau', top_pct=top_pct, maximize=maximize,
                                      grid_candidates=grid_candidates)
        X = []
        rows = []
        for p, val in top_runs:
            row = [float(p.get(k, 0)) for k in grid_keys]
            X.append(row)
            rows.append((p, val))
        if len(X) < n_clusters:
            return select_final_params(all_results, method='plateau', top_pct=top_pct, maximize=maximize,
                                      grid_candidates=grid_candidates)
        X = StandardScaler().fit_transform(X)
        kmeans = KMeans(n_clusters=min(n_clusters, len(X)), random_state=42, n_init=10)
        labels = kmeans.fit_predict(X)
        # 最大簇
        cnt = Counter(labels)
        largest_label = cnt.most_common(1)[0][0]
        cluster_rows = [rows[i] for i in range(len(rows)) if labels[i] == largest_label]
        # 簇内中位数落回网格
        final = {}
        for k in param_keys:
            if k not in grid_keys:
                final[k] = cluster_rows[0][0].get(k)
                continue
            values = [r[0][k] for r in cluster_rows if k in r[0]]
            if not values:
                final[k] = cluster_rows[0][0].get(k)
                continue
            median_val = sorted(float(x) for x in values)[len(values) // 2]
            if k in grid_candidates and grid_candidates[k]:
                v = _closest_in_list(median_val, grid_candidates[k])
                final[k] = int(v) if all(isinstance(x, int) for x in grid_candidates[k]) else v
            else:
                final[k] = int(median_val) if all(isinstance(x, int) for x in values) else median_val
        for k in param_keys:
            if k not in final:
                final[k] = cluster_rows[0][0].get(k)
        chosen_value = next((val for p, val in all_results if _params_match(p, final)), all_results[0][1])
        return final, chosen_value

    # ---------- robust：综合性能排名与稳健性排名 ----------
    if method == 'robust':
        metric_vals = [r[1] for r in all_results]
        bad = float('-inf') if maximize else float('inf')
        ranks_metric = _rank_values(metric_vals, maximize)
        robustness_scores = [compute_robustness_score(i, all_results, grid_candidates, metric_idx=1, radius=robust_radius) for i in range(len(all_results))]
        ranks_robust = _rank_values(robustness_scores, True)
        composite = [robust_alpha * ranks_metric[i] + (1 - robust_alpha) * ranks_robust[i] for i in range(len(all_results))]
        best_idx = max(range(len(composite)), key=lambda i: composite[i])
        final = all_results[best_idx][0].copy()
        chosen_value = all_results[best_idx][1]
        return final, chosen_value

    return all_results[0][0].copy(), all_results[0][1]


def _rank_values(values, higher_better=True):
    """返回排名（0 到 len-1），同分同排名取平均。higher_better 时值越大排名越高。"""
    n = len(values)
    if n == 0:
        return []
    sorted_pairs = sorted(enumerate(values), key=lambda x: (x[1] if x[1] is not None else (float('-inf') if higher_better else float('inf'))), reverse=higher_better)
    ranks = [0.0] * n
    for r, (i, _) in enumerate(sorted_pairs):
        ranks[i] = r
    return ranks


def _expand_param_grid(param_grid):
    """将 {k: [v1,v2], ...} 展开为 [(k1,v1,k2,v2,...), ...] 的笛卡尔积。"""
    keys = list(param_grid.keys())
    values = [param_grid[k] for k in keys]
    for combo in itertools.product(*values):
        yield dict(zip(keys, combo))


def _params_to_dict(strat):
    """将 backtrader 策略的 params (AutoInfoClass) 转为普通 dict。"""
    if not hasattr(strat, 'params'):
        return {}
    p = strat.params
    if hasattr(p, '_getitems'):
        return {name: getattr(p, name) for name, _ in p._getitems()}
    try:
        return dict(p)
    except (TypeError, ValueError):
        return {k: getattr(p, k) for k in dir(p) if not k.startswith('_') and not callable(getattr(p, k, None))}


def _get_returns(strategy_instance):
    """从 TimeReturn 取日收益序列（dict -> Series）。"""
    if strategy_instance is None:
        return None
    if isinstance(strategy_instance, (list, tuple)) and len(strategy_instance) > 0:
        strategy_instance = strategy_instance[0]
    a = getattr(strategy_instance.analyzers, 'returns', None)
    if a is None or not hasattr(a, 'get_analysis'):
        return None
    try:
        import pandas as pd
        d = a.get_analysis()
        if not d:
            return None
        s = pd.Series(d)
        s.index = pd.to_datetime(s.index)
        return s
    except Exception:
        return None


def _extract_metric(strategy_instance, metric='sharperatio'):
    """
    从策略实例的 analyzers 中取出指定指标。
    支持: sharperatio, final_value, drawdown, cagr, calmar, sortino, win_rate, profit_factor。
    """
    if strategy_instance is None:
        return None
    if isinstance(strategy_instance, (list, tuple)) and len(strategy_instance) > 0:
        strategy_instance = strategy_instance[0]
    name = metric.lower().strip()

    if name == 'sharperatio' or name == 'sharpe':
        a = getattr(strategy_instance.analyzers, 'sharpe', None)
        if a is not None and hasattr(a, 'get_analysis'):
            an = a.get_analysis()
            if an and 'sharperatio' in an and an['sharperatio'] is not None:
                return float(an['sharperatio'])
        return None
    if name == 'final_value' or name == 'value':
        return strategy_instance.broker.get_value()
    if name in ('drawdown', 'max_drawdown'):
        a = getattr(strategy_instance.analyzers, 'drawdown', None)
        if a is not None and hasattr(a, 'get_analysis'):
            an = a.get_analysis()
            if an and 'max' in an and 'drawdown' in an.get('max', {}):
                return float(an['max']['drawdown'])
        return None

    # 需收益序列的指标
    rets = _get_returns(strategy_instance)
    if name == 'cagr':
        if rets is None or len(rets) < 2:
            return None
        total_ret = (1 + rets).prod() - 1
        days = (rets.index[-1] - rets.index[0]).days
        years = days / 365.25 if days > 0 else 0
        if years <= 0:
            return None
        return float((1 + total_ret) ** (1 / years) - 1)
    if name == 'calmar':
        cagr_val = _extract_metric(strategy_instance, 'cagr')
        max_dd = _extract_metric(strategy_instance, 'drawdown')
        if cagr_val is None or max_dd is None or max_dd == 0:
            return None
        # max_dd 为百分数（如 15.5 表示 15.5%），Calmar = CAGR / (|max_dd|/100)
        return float(cagr_val / (abs(max_dd) / 100.0))
    if name == 'sortino':
        if rets is None or len(rets) < 2:
            return None
        import numpy as np
        rf = 0.0
        excess = rets - rf
        downside = excess[excess < 0]
        if len(downside) == 0 or downside.std() == 0:
            return None
        downside_std = downside.std() * np.sqrt(252)
        mean_excess = excess.mean() * 252
        return float(mean_excess / downside_std) if downside_std != 0 else None

    # 交易统计
    a = getattr(strategy_instance.analyzers, 'trades', None)
    if a is None or not hasattr(a, 'get_analysis'):
        if name in ('win_rate', 'profit_factor'):
            return None
    else:
        an = a.get_analysis()
        if name == 'win_rate':
            tot = an.get('total', {})
            if not isinstance(tot, dict):
                tot = {}
            total = tot.get('closed', 0) or tot.get('total', 0)
            w = an.get('won', {})
            if not isinstance(w, dict):
                w = {}
            won = w.get('total', 0) or w.get('closed', 0)
            if total is None or total == 0:
                return None
            return float(won / total)
        if name == 'profit_factor':
            pnl_won = (an.get('won') or {}).get('pnl', {}) if isinstance(an.get('won'), dict) else {}
            pnl_lost = (an.get('lost') or {}).get('pnl', {}) if isinstance(an.get('lost'), dict) else {}
            gross_profit = pnl_won.get('total', 0) or pnl_won.get('gross', 0) or 0
            gross_loss = pnl_lost.get('total', 0) or pnl_lost.get('gross', 0) or 0
            if gross_loss == 0:
                return float(gross_profit) if gross_profit else None
            try:
                return float(gross_profit / abs(float(gross_loss)))
            except (TypeError, ZeroDivisionError):
                return None

    return None


# 综合指标中“越低越好”的指标（优化时取负再参与加权，使统一为越大越好）
_LOWER_IS_BETTER = {'drawdown', 'max_drawdown'}


def compute_composite_score(results_with_metrics, composite_weights, maximize=True):
    """
    将 [(params, metrics_dict), ...] 按 composite_weights 加权归一化后得到综合得分。
    composite_weights: {"sharperatio": 0.4, "calmar": 0.3, "win_rate": 0.2, "drawdown": 0.1}
    对 _LOWER_IS_BETTER 中的指标会先取负再归一化，使“回撤越小”等价于“得分越高”。
    返回: [(params, composite_value), ...]，已按 composite_value 排序（最优在前）。
    """
    if not results_with_metrics or not composite_weights:
        return []
    weights = {k.lower().strip(): float(v) for k, v in composite_weights.items() if v != 0}
    if not weights:
        return [(p, 0.0) for p, _ in results_with_metrics]
    keys = list(weights.keys())
    # 按列收集值
    cols = {k: [] for k in keys}
    for _, m in results_with_metrics:
        for k in keys:
            v = m.get(k) if isinstance(m, dict) else None
            if v is None:
                try:
                    v = m.get(k.upper(), m.get(k.lower(), None))
                except Exception:
                    pass
            if v is not None and not isinstance(v, (int, float)):
                try:
                    v = float(v)
                except (TypeError, ValueError):
                    v = None
            cols[k].append(v)

    # 归一化到 [0,1]，缺失用 0.5
    import math
    normalized = []
    for i in range(len(results_with_metrics)):
        score = 0.0
        for k in keys:
            vals = [x for x in cols[k] if x is not None]
            if not vals:
                score += weights[k] * 0.5
                continue
            v = cols[k][i]
            if v is None:
                score += weights[k] * 0.5
                continue
            lo, hi = min(vals), max(vals)
            if hi == lo:
                norm = 0.5
            else:
                norm = (v - lo) / (hi - lo)
                if k in _LOWER_IS_BETTER:
                    norm = 1.0 - norm  # 回撤越小越好 -> 归一化后越大越好
            score += weights[k] * norm
        normalized.append(score)
    out = [(results_with_metrics[i][0], normalized[i]) for i in range(len(results_with_metrics))]
    out.sort(key=lambda x: x[1], reverse=True)
    return out


def grid_search(cerebro_factory, strategy_cls, param_grid, metric='sharperatio', maximize=True, logger=None):
    """
    网格搜索：对 param_grid 的笛卡尔积逐一运行 cerebro，比较 metric，返回最优参数字典与全部结果。
    cerebro_factory: 可调用 (data_dict, strategy_cls, strategy_params) -> (cerebro 实例, 无策略无数据)
    要求返回的 cerebro 已 set_capital/set_costs，且本函数会 addstrategy + load_data + run。
    为简化，这里改为：cerebro_factory() 返回已配置好 data 的 cerebro，然后我们 addstrategy(策略, **params) 并 run。
    更简单：cerebro_factory(strategy_params) 返回一个已添加好该参数策略并 load 好数据的 cerebro，我们只 run 并取结果。
    """
    log = logger or Logger()
    results = []
    for params in _expand_param_grid(param_grid):
        try:
            cerebro = cerebro_factory(params)
            if cerebro is None:
                continue
            run_result = cerebro.run()
            # run_result 是 list of strategy instances (每个 strategy 一个)
            strat = run_result[0] if run_result else None
            value = _extract_metric(strat, metric)
            results.append((params, value, strat))
        except Exception as e:
            if logger:
                log.warning(f"参数 {params} 运行失败: {e}")
            results.append((params, None, None))

    # 最优：按 value 排序，None 视作最差
    def key_fn(item):
        p, v, _ = item
        if v is None:
            return float('-inf') if maximize else float('inf')
        return v if maximize else -v

    results.sort(key=key_fn, reverse=maximize)
    best_params = results[0][0] if results else {}
    best_value = results[0][1] if results else None
    return best_params, best_value, results


def run_optstrategy(cerebro, strategy_cls, param_grid, metric='sharperatio', maximize=True):
    """
    使用 Backtrader 自带的 optstrategy：一次性对所有参数组合跑完，返回最优参数与结果列表。
    cerebro 需已 load_data、set_capital、set_costs；本函数只 addoptstrategy 并 run。
    param_grid 格式：{'atr_period': [10,14,20], 'risk_per_trade_pct': [0.02, 0.03]}。
    """
    # Backtrader addstrategy 可变参数：addstrategy(Strat, p1=val1, p2=val2)
    # optstrategy: addstrategy(Strat, p1=[v1,v2], p2=[v3,v4]) 会跑 2*2=4 次
    kwargs = dict(param_grid)
    cerebro.optstrategy(strategy_cls, **kwargs)
    run_results = cerebro.run()
    # optstrategy 时 run 返回的是 list of list: 每个组合一个 list，里面一个 strategy instance
    strategies_flat = []
    for x in run_results:
        if isinstance(x, (list, tuple)):
            strategies_flat.extend(x)
        else:
            strategies_flat.append(x)

    results = []
    for strat in strategies_flat:
        params = _params_to_dict(strat)
        value = _extract_metric(strat, metric)
        results.append((params, value, strat))

    def key_fn(item):
        _, v, _ = item
        if v is None:
            return float('-inf') if maximize else float('inf')
        return v if maximize else -v

    results.sort(key=key_fn, reverse=maximize)
    best_params = results[0][0] if results else {}
    best_value = results[0][1] if results else None
    return best_params, best_value, results


def walk_forward_analysis(cerebro_factory, strategy_cls, param_grid, train_days, test_days,
                          from_date, to_date, data_dir, universe_size=None,
                          metric='sharperatio', maximize=True, logger=None):
    """
    向前步进分析：将区间按 train_days / test_days 滚动划分，每段用 train 区间（可选做网格搜索）选参，
    test 区间用该参数跑并记录 test 指标，最后汇总（如平均 Sharpe）。
    cerebro_factory: (start, end, strategy_params) -> cerebro 已配置好该时间段数据与策略。
    简化：我们只做固定参数在滚动窗口上的表现，param_grid 若多组则对每组做 WFA，再比平均指标。
    """
    import pandas as pd
    log = logger or Logger()
    # 生成滚动窗口
    from_ts = pd.Timestamp(from_date)
    to_ts = pd.Timestamp(to_date)
    results_per_params = defaultdict(list)

    for params in _expand_param_grid(param_grid):
        current = from_ts
        test_metrics = []
        while current + pd.Timedelta(days=train_days + test_days) <= to_ts:
            train_end = current + pd.Timedelta(days=train_days)
            test_end = current + pd.Timedelta(days=train_days + test_days)
            try:
                cerebro = cerebro_factory(
                    train_end - pd.Timedelta(days=train_days), train_end,
                    strategy_cls, params
                )
                if cerebro is None:
                    current = current + pd.Timedelta(days=test_days)
                    continue
                cerebro.run()
                # 在 test 区间上跑（用同一 params）
                cerebro2 = cerebro_factory(
                    train_end, test_end,
                    strategy_cls, params
                )
                if cerebro2 is None:
                    current = current + pd.Timedelta(days=test_days)
                    continue
                run_result = cerebro2.run()
                strat = run_result[0] if run_result else None
                value = _extract_metric(strat, metric)
                if value is not None:
                    test_metrics.append(value)
            except Exception as e:
                if logger:
                    log.warning(f"WFA 窗口 {current}~{test_end} 失败: {e}")
            current = current + pd.Timedelta(days=test_days)

        if test_metrics:
            avg = sum(test_metrics) / len(test_metrics)
            results_per_params[tuple(sorted(params.items()))].append(avg)

    # 对每组参数取平均 metric，选最优
    best_params = None
    best_avg = float('-inf') if maximize else float('inf')
    results = []
    for param_tup, values in results_per_params.items():
        avg = sum(values) / len(values)
        params = dict(param_tup)
        results.append((params, avg, values))
        if maximize and avg > best_avg:
            best_avg = avg
            best_params = params
        elif not maximize and avg < best_avg:
            best_avg = avg
            best_params = params

    results.sort(key=lambda x: x[1], reverse=maximize)
    best_params = results[0][0] if results else {}
    return best_params, best_avg, results


def validate_parameter_selection(cerebro_factory, strategy_cls, selected_params, train_days, test_days,
                                from_date, to_date, metric='sharperatio', logger=None):
    """
    多时间窗口/样本外验证：用选定参数在多个滚动窗口的测试段上回测，返回各窗口指标及均值、标准差。
    cerebro_factory: (start, end, strategy_cls, params) -> cerebro
    返回: {'mean': float, 'std': float, 'per_window': [(test_start, test_end, metric_value), ...]}
    """
    import pandas as pd
    log = logger or Logger()
    from_ts = pd.Timestamp(from_date)
    to_ts = pd.Timestamp(to_date)
    per_window = []
    current = from_ts
    while current + pd.Timedelta(days=train_days + test_days) <= to_ts:
        train_end = current + pd.Timedelta(days=train_days)
        test_end = current + pd.Timedelta(days=train_days + test_days)
        try:
            cerebro = cerebro_factory(train_end, test_end, strategy_cls, selected_params)
            if cerebro is None:
                current = current + pd.Timedelta(days=test_days)
                continue
            run_result = cerebro.run()
            strat = run_result[0] if run_result else None
            value = _extract_metric(strat, metric)
            if value is not None:
                per_window.append((train_end, test_end, value))
        except Exception as e:
            if logger:
                log.warning(f"验证窗口 {train_end}~{test_end} 失败: {e}")
        current = current + pd.Timedelta(days=test_days)

    if not per_window:
        return {'mean': None, 'std': None, 'per_window': []}
    values = [x[2] for x in per_window]
    mean_v = sum(values) / len(values)
    variance = sum((x - mean_v) ** 2 for x in values) / len(values)
    std_v = variance ** 0.5
    return {'mean': mean_v, 'std': std_v, 'per_window': per_window}


def run_bayesian_optimization(param_grid, fixed_params, run_backtest_func, n_calls=50, maximize=True,
                              random_state=42, logger=None):
    """
    贝叶斯优化（需 scikit-optimize）：在连续/离散参数空间上优化，调用 run_backtest_func(params_dict) 得到指标。
    param_grid: 仅网格键与候选值，如 {'atr_period': [10, 14, 20], 'risk_per_trade_pct': [0.02, 0.03, 0.04]}
    fixed_params: 固定参数，与 param_grid 合并成完整 params 传入 run_backtest_func。
    run_backtest_func: (params_dict) -> metric_value (float or None)
    n_calls: 贝叶斯优化迭代次数。
    返回: (best_params_dict, best_value)
    """
    try:
        from skopt import gp_minimize
        from skopt.space import Integer, Real, Categorical
    except ImportError:
        if logger:
            logger.warning("未安装 scikit-optimize (pip install scikit-optimize)，无法运行贝叶斯优化")
        return {}, None

    log = logger or Logger()
    param_names = []
    dimensions = []
    for k, vals in param_grid.items():
        if not vals:
            continue
        param_names.append(k)
        if all(isinstance(v, int) for v in vals):
            dimensions.append(Integer(min(vals), max(vals), name=k))
        elif all(isinstance(v, (int, float)) for v in vals):
            dimensions.append(Real(min(vals), max(vals), name=k))
        else:
            dimensions.append(Categorical(vals, name=k))

    if not dimensions:
        return {}, None

    def objective(x):
        # x 是 list，与 dimensions 顺序一致；Categorical 时 x 是索引
        params_list = list(x)
        d = {}
        for i, k in enumerate(param_names):
            if i >= len(params_list):
                break
            v = params_list[i]
            vals = param_grid[k]
            if all(isinstance(vv, int) for vv in vals) and isinstance(v, float):
                v = int(round(v))
            if isinstance(dimensions[i], Categorical):
                v = vals[int(v)] if isinstance(v, (int, float)) else v
            d[k] = v
        full = {**fixed_params, **d}
        try:
            metric_val = run_backtest_func(full)
            if metric_val is None:
                return float('-inf') if maximize else float('inf')
            return float(metric_val)
        except Exception as e:
            if log:
                log.warning(f"贝叶斯优化单次运行失败: {e}")
            return float('-inf') if maximize else float('inf')

    result = gp_minimize(
        lambda x: -objective(x) if maximize else objective(x),
        dimensions,
        n_calls=n_calls,
        random_state=random_state,
        n_initial_points=min(5, n_calls),
    )
    best_x = result.x
    best_params = {}
    for i, k in enumerate(param_names):
        if i >= len(best_x):
            break
        v = best_x[i]
        vals = param_grid[k]
        if isinstance(dimensions[i], Categorical):
            v = vals[int(v)] if (isinstance(v, (int, float)) and 0 <= int(v) < len(vals)) else (v if v in vals else vals[0])
        elif all(isinstance(vv, int) for vv in vals) and isinstance(v, float):
            v = int(round(v))
            v = min(max(v, min(vals)), max(vals))
        best_params[k] = v
    full_best = {**fixed_params, **best_params}
    best_value = run_backtest_func(full_best) if result.fun is not None else None
    if maximize and best_value is None:
        best_value = -result.fun
    elif not maximize and best_value is None:
        best_value = result.fun
    return full_best, best_value
