"""参数选择策略单元测试：best / plateau / robust（不依赖 sklearn/scipy）"""
import pytest
from engine.optimizer import (
    select_final_params,
    compute_robustness_score,
    _params_match,
    _params_in_results,
    _snap_params_to_grid,
    _grid_param_index,
    _closest_in_list,
    _get_top_runs_by_pct_or_threshold,
)


class TestSelectFinalParamsBest:
    def test_best_returns_first(self):
        results = [
            ({"a": 1, "b": 0.02}, 10.0),
            ({"a": 2, "b": 0.03}, 8.0),
        ]
        params, val = select_final_params(results, method="best", maximize=True)
        assert params == {"a": 1, "b": 0.02}
        assert val == 10.0


class TestSelectFinalParamsPlateau:
    def test_plateau_median_snap_to_grid(self):
        results = [
            ({"atr_period": 10, "risk": 0.02}, 5.0),
            ({"atr_period": 14, "risk": 0.02}, 6.0),
            ({"atr_period": 20, "risk": 0.03}, 4.0),
        ]
        grid = {"atr_period": [10, 14, 20], "risk": [0.02, 0.03]}
        params, _ = select_final_params(
            results, method="plateau", top_pct=1.0, maximize=True, grid_candidates=grid
        )
        assert params["atr_period"] in [10, 14, 20]
        assert params["risk"] in [0.02, 0.03]


class TestSelectFinalParamsPlateauFreq:
    """改进 Plateau：优秀组合中每参数取频率最高的值，落回网格。"""

    def test_plateau_freq_mode_snap_to_grid(self):
        # 前 20% 为 2 条： (14, 0.02) 出现 2 次，(10, 0.02) 出现 1 次 -> atr 众数 14，risk 众数 0.02
        results = [
            ({"atr_period": 14, "risk": 0.02}, 10.0),
            ({"atr_period": 14, "risk": 0.02}, 9.0),
            ({"atr_period": 10, "risk": 0.02}, 8.0),
            ({"atr_period": 20, "risk": 0.03}, 7.0),
            ({"atr_period": 10, "risk": 0.03}, 6.0),
        ]
        grid = {"atr_period": [10, 14, 20], "risk": [0.02, 0.03]}
        params, _ = select_final_params(
            results, method="plateau_freq", top_pct=0.4, maximize=True, grid_candidates=grid
        )
        assert params["atr_period"] == 14
        assert params["risk"] == 0.02

    def test_plateau_freq_threshold_filter(self):
        # 用阈值筛选：metric >= 8 的只有前 3 条，其中 atr 14 出现 2 次、10 出现 1 次 -> 众数 14
        results = [
            ({"a": 14, "b": 1}, 10.0),
            ({"a": 14, "b": 1}, 9.0),
            ({"a": 10, "b": 2}, 8.0),
            ({"a": 10, "b": 2}, 7.0),
        ]
        grid = {"a": [10, 14], "b": [1, 2]}
        params, _ = select_final_params(
            results, method="plateau_freq", top_pct=0.5, maximize=True,
            grid_candidates=grid, plateau_threshold=8.0,
        )
        assert params["a"] == 14
        assert params["b"] == 1

    def test_get_top_runs_by_threshold(self):
        results = [({"x": i}, 10 - i) for i in range(5)]  # 10, 9, 8, 7, 6
        top = _get_top_runs_by_pct_or_threshold(results, top_pct=0.4, plateau_threshold=8.0, maximize=True)
        assert len(top) == 3  # 10, 9, 8
        top2 = _get_top_runs_by_pct_or_threshold(results, top_pct=0.4, plateau_threshold=None, maximize=True)
        assert len(top2) == 2  # 20% of 5 = 1 -> max(1,1)=1, so 1? Actually n = max(1, int(5*0.4)) = 2
        assert len(top2) == 2


class TestParamsHelpers:
    def test_params_match(self):
        assert _params_match({"a": 1, "b": 2}, {"a": 1, "b": 2}) is True
        assert _params_match({"a": 1, "b": 2.0}, {"a": 1, "b": 2}) is True
        assert _params_match({"a": 1}, {"a": 1, "b": 2}) is False

    def test_closest_in_list(self):
        assert _closest_in_list(13.5, [10, 14, 20]) == 14
        assert _closest_in_list(15, [10, 14, 20]) == 14

    def test_snap_to_grid(self):
        out = _snap_params_to_grid({"a": 13.2, "b": 0.025}, {"a": [10, 14, 20], "b": [0.02, 0.03]})
        assert out["a"] == 14
        assert out["b"] in [0.02, 0.03]
