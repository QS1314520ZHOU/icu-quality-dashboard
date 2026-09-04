"""
升压药剂量换算适配器。
唯一换算点：所有 ug/kg/min 计算必须经过 ne_ugkgmin()。
salt_form 永远填 BASE——换算已在本模块完成，salt_form 描述的是传入 dose 的口径。

需求文档 7.3 第 10、11 条:
  - salt_form 必须传 enum 成员，不允许字符串
  - MedicationAdministration 使用 dataclass + __post_init__ 校验
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Optional

import config.indicator_windows as _cfg


# ---- 枚举 ----
class SaltForm(StrEnum):
    """NE 盐型枚举。BASE=碱基计，SALT=盐型计。"""
    BASE = "base"
    SALT = "salt"


# ---- 常量 ----
_LABEL_TO_BASE = {SaltForm.BASE: 1.0, SaltForm.SALT: 0.5}

# dose 单位白名单(小写比较)
ValidDoseUnit = {"mg", "毫克"}
# liquidAmount 单位白名单(小写比较)
ValidLiquidUnit = {"ml", "ml", "毫升"}

# 体重有效范围(kg)
WEIGHT_MIN = 20.0
WEIGHT_MAX = 300.0

# 剂量异常高值阈值(ug/kg/min)，超过需人工复核
DOSE_REVIEW_THRESHOLD = 2.0


@dataclass
class MedicationAdministration:
    """结构化用药执行记录。salt_form 永远为 BASE。"""
    drug_name: str
    dose_mg: float           # 原始 dose 值(标签口径)
    dose_unit: str           # 原始 dose 单位
    liquid_amount_ml: float  # 配液总量(ml)
    speed_mlh: float         # 泵速(ml/h)
    weight_kg: float         # 患者体重(kg)
    salt_form: SaltForm = SaltForm.BASE  # 固定值——换算已在 ne_ugkgmin 中完成

    def __post_init__(self):
        # 需求文档 7.3 第 10 条: salt_form 必须为 enum 成员
        if not isinstance(self.salt_form, SaltForm):
            raise TypeError(
                f"salt_form 必须为 SaltForm 枚举成员, 不允许字符串. "
                f"收到: {type(self.salt_form).__name__}({self.salt_form!r})"
            )
        if self.salt_form != SaltForm.BASE:
            raise ValueError(
                f"salt_form 必须为 BASE，换算只允许在 ne_ugkgmin 中进行。"
                f"收到: {self.salt_form}"
            )


def _safe_float(val) -> Optional[float]:
    """安全转 float，失败返回 None。"""
    if val is None:
        return None
    try:
        return float(val)
    except (TypeError, ValueError):
        return None


def ne_ugkgmin(action: dict, weight_kg: float) -> tuple[Optional[float], list[str]]:
    """
    去甲肾上腺素剂量换算(唯一换算点)。

    参数:
        action: drugExe 文档或其 drugList 子项，需含:
            - dose: 药量值
            - unit: 药量单位(mg/毫克)
            - liquidAmount: 配液总量(ml)
            - speed: 泵速(ml/h)(可选，来自 drugActionList)
        weight_kg: 患者体重(kg)

    返回:
        (ug_per_kg_min, data_quality_flags)
        - ug_per_kg_min: 换算结果或 None
        - data_quality_flags: 问题描述列表(空=无问题)
    """
    flags = []
    basis_str = _cfg.NE_LABEL_BASIS

    # ---- 2.5 NE_LABEL_BASIS 检查 ----
    try:
        basis = SaltForm(basis_str)
    except ValueError:
        flags.append(
            f"NE_LABEL_BASIS 未配置（当前值: {basis_str!r}, "
            f"允许: {[e.value for e in SaltForm]}，需药师签字），拒绝计算 CV 剂量分"
        )
        return None, flags

    base_factor = _LABEL_TO_BASE[basis]

    # ---- 2.2 dose 单位白名单 ----
    dose_raw = _safe_float(action.get("dose"))
    dose_unit = (action.get("unit") or "").strip().lower()
    if dose_unit not in ValidDoseUnit:
        flags.append(f"dose 单位不在白名单: '{action.get('unit')}'（允许: mg/毫克），拒绝计算")
        return None, flags

    # ---- 2.2 liquidAmount 单位白名单 ----
    # liquidAmount 可能在 action 子项或父文档顶层
    liquid_raw = _safe_float(action.get("liquidAmount"))
    liquid_unit = (action.get("liquidAmountUnit") or "ml").strip().lower()
    if liquid_unit not in ValidLiquidUnit:
        flags.append(f"liquidAmount 单位不在白名单: '{action.get('liquidAmountUnit')}'（允许: ml/mL/毫升），拒绝计算")
        return None, flags

    # ---- 2.3 liquidAmount <= 0 防除零 ----
    if liquid_raw is None or liquid_raw <= 0:
        flags.append(f"liquidAmount 无效: {liquid_raw}，拒绝计算")
        return None, flags

    # ---- dose 有效性 ----
    if dose_raw is None or dose_raw <= 0:
        flags.append(f"dose 无效: {action.get('dose')}，拒绝计算")
        return None, flags

    # ---- 2.1 浓度逐医嘱计算 ----
    concentration_mg_ml = dose_raw / liquid_raw

    # ---- speed ----
    speed = _safe_float(action.get("speed"))
    if speed is None or speed <= 0:
        flags.append(f"speed 无效: {action.get('speed')}，拒绝计算")
        return None, flags

    # ---- 2.4 体重过滤 ----
    if weight_kg is None or weight_kg < WEIGHT_MIN or weight_kg > WEIGHT_MAX:
        flags.append(f"体重超范围: {weight_kg}kg（有效范围 {WEIGHT_MIN}-{WEIGHT_MAX}kg），拒绝计算")
        return None, flags

    # ---- 核心换算 ----
    # ug/kg/min = concentration(mg/ml) × speed(ml/h) / 60 / weight(kg) × 1000 × base_factor
    result = concentration_mg_ml * speed / 60.0 / weight_kg * 1000.0 * base_factor

    # ---- 2.6 异常高值标记 ----
    if result > DOSE_REVIEW_THRESHOLD:
        flags.append(f"剂量 {result:.3f} ug/kg/min 超过 {DOSE_REVIEW_THRESHOLD}，需人工复核")

    return round(result, 4), flags


def build_medication_administration(
    drug: dict,
    doc: dict,
    weight_kg: float,
    speed_mlh: float,
) -> Optional[MedicationAdministration]:
    """
    从 drugExe 子项构建 MedicationAdministration。
    salt_form 固定为 BASE。
    """
    dose = _safe_float(drug.get("dose"))
    liquid = _safe_float(drug.get("liquidAmount")) or _safe_float(doc.get("liquidAmount"))
    if dose is None or liquid is None:
        return None
    return MedicationAdministration(
        drug_name=drug.get("name", ""),
        dose_mg=dose,
        dose_unit=drug.get("unit", ""),
        liquid_amount_ml=liquid,
        speed_mlh=speed_mlh,
        weight_kg=weight_kg,
        salt_form=SaltForm.BASE,  # 固定值，见模块文档
    )
