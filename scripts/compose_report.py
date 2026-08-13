#!/usr/bin/env python3
"""Compose a qualification big-data report by orchestrating the qualification MCP.

Calls the upstream qualification-mcp-server tools and assembles a structured JSON
payload rendered into a professional HTML / Markdown report. Supports
``--dry-run`` which returns a well-formed skeleton from the bundled sample data
WITHOUT contacting the MCP.

Workflow (real run):
  1. Resolve the canonical enterprise name (fuzzy search if only a keyword).
  2. Query qualification_certificate_profile (证书概况), honor_qualifications (荣誉),
     enterprise_qualifications (企业资质), administrative_licenses (行政许可),
     hitech_enterprise_cert (高新技术企业认证).
  3. Build unified report JSON with domain sections.
  4. Optionally render HTML + Markdown.

This file never prints secrets; MCP credentials live in the server's own .env.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import pathlib
import sys
from typing import Any, Dict, List, Mapping, Optional

from common import REPORT_BANNER, REPORT_TYPE, json_dumps, load_json_file, print_json
import mcp_client
from render_report import render_html, render_markdown, html_to_pdf

SAMPLE_PATH = pathlib.Path(__file__).resolve().parent.parent / "assets" / "report.example.json"

# Qualification MCP tools.
T_FUZZY = "qualification_bigdata_fuzzy_search"
T_HONOR = "qualification_bigdata_honor_qualifications"
T_ENTERPRISE = "qualification_bigdata_enterprise_qualifications"
T_LICENSE = "qualification_bigdata_administrative_licenses"
T_PROFILE = "qualification_bigdata_qualification_certificate_profile"
T_HITECH = "qualification_bigdata_hitech_enterprise_cert"


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #


def _is_api_error(value: Any) -> bool:
    """Detect MCP API error responses (not empty data, but actual failures like 405)."""
    if value is None:
        return False
    if isinstance(value, str):
        return any(s in value for s in ("接口调用失败", "查询失败", "状态码：4", "状态码：5"))
    if isinstance(value, dict):
        for v in value.values():
            if isinstance(v, str) and any(s in v for s in ("接口调用失败", "查询失败", "状态码：4", "状态码：5")):
                return True
    return False

def _first_list(value: Any) -> List[Any]:
    if isinstance(value, list):
        return value
    if isinstance(value, dict):
        if _is_api_error(value):
            return []
        for key in ("resultList", "list", "items", "data"):
            if isinstance(value.get(key), list):
                return value[key]
    if value in (None, "", {}):
        return []
    return [value]


def _first_record(value: Any) -> Dict[str, Any]:
    for record in _first_list(value):
        if isinstance(record, dict):
            return record
    if isinstance(value, dict):
        return value
    return {}


def _text(value: Any, limit: int = 0) -> str:
    if value is None:
        return ""
    if isinstance(value, (dict, list)):
        t = json.dumps(value, ensure_ascii=False)
    else:
        t = str(value)
    t = " ".join(t.split())
    if limit and len(t) > limit:
        return t[: limit - 1].rstrip() + "…"
    return t


def _int(value: Any) -> Optional[int]:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _safe_call(tool: str, arguments: Dict[str, Any]) -> Any:
    try:
        result = mcp_client.call_tool(tool, arguments)
        # Detect API error responses (405, etc.) and return error marker
        if _is_api_error(result):
            return {"_error": "API错误", "_raw": result}
        return result
    except Exception as exc:
        return {"_error": str(exc)}


def _safe_total(payload: Any) -> Any:
    if isinstance(payload, dict):
        if _is_api_error(payload):
            return None
        return payload.get("total")
    return None


def _concentration(rows: List[Mapping[str, Any]], name_key: str, value_key: str, top_n: int = 3) -> Dict[str, Any]:
    """Compute top-N concentration (CRn) and dominant category from {name,count} rows."""
    items = []
    for r in rows:
        try:
            items.append((r.get(name_key, "-"), float(str(r.get(value_key, 0)).replace(",", ""))))
        except (TypeError, ValueError):
            items.append((r.get(name_key, "-"), 0.0))
    total = sum(v for _, v in items)
    if not total:
        return {}
    items.sort(key=lambda x: x[1], reverse=True)
    cr = sum(v for _, v in items[:top_n]) / total * 100
    return {"top": items[0][0], "top_share": items[0][1] / total * 100, "cr": cr, "total": total, "n": len(items)}


# --------------------------------------------------------------------------- #
# Resolution
# --------------------------------------------------------------------------- #

def resolve_enterprise_name(raw: str) -> Dict[str, Any]:
    raw = (raw or "").strip()
    if not raw:
        return {"keyword": "", "enterprise": "", "resolved": False, "reason": "关键词为空"}
    if any(suffix in raw for suffix in ("公司", "集团", "有限", "院", "厂", "中心", "事务所", "合作社", "合伙")):
        return {"keyword": raw, "enterprise": raw, "resolved": True, "reason": "视为企业全称"}
    fuzzy = _safe_call(T_FUZZY, {"matchKeyword": raw, "pageSize": 1})
    record = _first_record(fuzzy)
    name = str(record.get("name") or "").strip()
    if name:
        return {"keyword": raw, "enterprise": name, "resolved": True, "reason": "由关键词模糊查询补全", "fuzzy_total": _int(_safe_total(fuzzy)), "record": record}
    return {"keyword": raw, "enterprise": raw, "resolved": False, "reason": "模糊查询未命中企业全称，按关键词直查"}


# --------------------------------------------------------------------------- #
# Enterprise profile helpers (from fuzzy_search record)
# --------------------------------------------------------------------------- #

def _extract_profile(record: Dict[str, Any]) -> Dict[str, Any]:
    """Extract enterprise profile fields from a fuzzy_search record."""
    return {
        "name": _text(record.get("name")),
        "reg_capital": record.get("regCapitalValue"),
        "reg_capital_coin": _text(record.get("regCapitalCoinType")),
        "annual_turnover": _text(record.get("annualTurnover")),
        "oper_status": _text(record.get("operStatus")),
        "enterprise_type": _text(record.get("enterpriseType")),
        "found_time": _text(record.get("foundTime")),
        "legal_rep": _text(record.get("legalRepresentative")),
        "address": _text(record.get("address")),
        "homepage": _text(record.get("homepage")),
    }


def _format_capital(val: Any, coin: str = "") -> str:
    """Format capital value: 10995210218.0 -> '109.95 亿'."""
    try:
        v = float(val)
        if v >= 1e8:
            s = f"{v / 1e8:.2f} 亿"
        elif v >= 1e4:
            s = f"{v / 1e4:.2f} 万"
        else:
            s = f"{v:.0f}"
        if coin:
            s += f" {coin}"
        return s
    except (TypeError, ValueError):
        return _text(val) if val else "-"


def _enrich_metrics_with_profile(metrics: List[Dict[str, Any]], record: Any) -> List[Dict[str, Any]]:
    """Append enterprise profile metrics from a fuzzy_search record."""
    if not isinstance(record, dict):
        return metrics
    _prof = _extract_profile(record)
    if _prof.get("reg_capital") and _prof["reg_capital"] not in ("-", "", None):
        metrics.append({"label": "注册资本", "value": _format_capital(_prof["reg_capital"], _prof.get("reg_capital_coin", "")), "hint": "工商登记注册资本"})
    if _prof.get("found_time") and _prof["found_time"] != "-":
        metrics.append({"label": "成立时间", "value": _prof["found_time"], "hint": "工商登记成立日期"})
    if _prof.get("oper_status") and _prof["oper_status"] != "-":
        metrics.append({"label": "经营状态", "value": _prof["oper_status"], "hint": "工商登记经营状态"})
    if _prof.get("enterprise_type") and _prof["enterprise_type"] != "-":
        metrics.append({"label": "企业类型", "value": _prof["enterprise_type"], "hint": "工商登记企业类型"})
    if _prof.get("legal_rep") and _prof["legal_rep"] != "-":
        metrics.append({"label": "法定代表人", "value": _prof["legal_rep"], "hint": "工商登记法定代表人"})
    return metrics


def _derive_core_metrics(metrics: List[Dict[str, Any]], core: Mapping[str, Any]) -> List[Dict[str, Any]]:
    """Derive additional metrics from core analysis sections."""
    cat_dist = core.get("category_dist", []) if isinstance(core, dict) else []
    honors = core.get("honor_records", []) if isinstance(core, dict) else []
    licenses = core.get("license_records", []) if isinstance(core, dict) else []
    hitech = core.get("hitech_records", []) if isinstance(core, dict) else []
    year_trend = core.get("cert_year_trend", []) if isinstance(core, dict) else []
    cert_profile = core.get("cert_profile", {}) if isinstance(core, dict) else {}
    if isinstance(cat_dist, list) and cat_dist:
        metrics.append({"label": "资质类别数", "value": str(len(cat_dist)), "hint": "不同资质证书类别数"})
    if isinstance(year_trend, list) and year_trend:
        metrics.append({"label": "获证年份跨度", "value": str(len(year_trend)), "hint": "有获证记录的年度数"})
    if isinstance(cert_profile, dict) and cert_profile:
        recent = cert_profile.get("近一年获证数量")
        if recent and str(recent) not in ("-", "", "0", "None"):
            metrics.append({"label": "近一年获证", "value": str(recent), "hint": "最近一年新获证书数量"})
    return metrics


# --------------------------------------------------------------------------- #
# Section builders
# --------------------------------------------------------------------------- #

def build_subject(raw: str, resolved: Mapping[str, Any], keyword_type: str) -> Dict[str, Any]:
    return {
        "enterprise": resolved.get("enterprise") or raw,
        "matchKeyword": resolved.get("enterprise") or raw,
        "keywordType": keyword_type,
        "match_raw": raw,
        "resolved": bool(resolved.get("resolved")),
        "resolve_reason": resolved.get("reason", ""),
    }


def build_metrics(profile: Mapping[str, Any], honor: Any, enterprise: Any, license_p: Any, hitech: Any, core: Mapping[str, Any] = None) -> List[Dict[str, Any]]:
    metrics: List[Dict[str, Any]] = []
    core = core or {}
    p = profile if isinstance(profile, dict) else {}
    cert_total = _int(p.get("certificateCount"))
    recent = _int(p.get("certNumberThisYear"))
    metrics.append({"label": "证书总数", "value": _text(p.get("certificateCount")) or "-", "hint": "企业资质证书总量"})
    if recent and cert_total:
        share = recent / cert_total * 100
        metrics.append({"label": "近一年获证", "value": _text(p.get("certNumberThisYear")) or "-", "hint": "最近一年获证数量", "delta": f"占总量 {share:.0f}%"})
    else:
        metrics.append({"label": "近一年获证", "value": _text(p.get("certNumberThisYear")) or "-", "hint": "最近一年获证数量"})
    metrics.append({"label": "荣誉资质", "value": str(_safe_total(honor) or len(_first_list(honor))) + " 条", "hint": "荣誉资质条数"})
    metrics.append({"label": "企业资质", "value": str(_safe_total(enterprise) or len(_first_list(enterprise))) + " 条", "hint": "企业资质条数"})
    metrics.append({"label": "行政许可", "value": str(_safe_total(license_p) or len(_first_list(license_p))) + " 条", "hint": "行政许可条数"})
    metrics.append({"label": "高新技术企业认证", "value": str(_safe_total(hitech) or len(_first_list(hitech))) + " 条", "hint": "高新技术企业认证条数"})
    # 资质类别聚类数 & 高新技术领域覆盖数（来自 enterprise 资质）
    class_rows = core.get("class_cluster") or []
    if class_rows:
        metrics.append({"label": "资质类别聚类", "value": str(len(class_rows)) + " 类", "hint": "qualificationClasses 去重数"})
    hitech_rows = core.get("hitech_industry") or []
    if hitech_rows:
        metrics.append({"label": "高新技术领域", "value": str(len(hitech_rows)) + " 个", "hint": "highTechIndustryList 去重领域数"})
    return [m for m in metrics if m.get("value") not in ("", None, "-")]


def build_caliber(subject: Mapping[str, Any]) -> Dict[str, Any]:
    return {
        "match_target": subject.get("enterprise") or subject.get("match_raw"),
        "match_type": f"资质大数据按企业主体匹配（keywordType={subject.get('keywordType', 'name')}）",
        "data_scope": "资质证书概况、荣誉资质、企业资质、行政许可、高新技术企业认证、资质类别聚类、高新技术领域覆盖、获证年度趋势",
        "products": ["资质证书概况", "荣誉资质", "企业资质", "行政许可", "高新技术企业认证"],
        "limit": "数据来自资质公开数据库；少量字段可能存在更新延迟。",
    }


def build_core_analysis(profile: Any, honor: Any, enterprise: Any, license_p: Any, hitech: Any) -> Dict[str, Any]:
    p = profile if isinstance(profile, dict) else {}

    # 资质证书概况 KV
    profile_kv: Dict[str, Any] = {}
    for k, label in (
        ("certificateCount", "证书总数"),
        ("certNumberThisYear", "近一年获证数量"),
        ("certFirstPublishTime", "初次获证日期"),
        ("certLastPublishTime", "最近获证日期"),
    ):
        if p.get(k) is not None:
            profile_kv[label] = _text(p.get(k))
    if isinstance(p.get("certTypeList"), list) and p["certTypeList"]:
        profile_kv["涵盖证书类别"] = "、".join(_text(t) for t in p["certTypeList"] if t)

    honor_rows = _build_honor_rows(honor)
    enterprise_rows = _build_enterprise_rows(enterprise)
    license_rows = _build_license_rows(license_p)
    hitech_rows = _build_hitech_rows(hitech)
    class_cluster_rows = _class_cluster_rows(enterprise)
    hitech_industry_rows = _hitech_industry_rows(enterprise)
    cert_year_rows = _cert_year_rows(enterprise)

    # 资质类别分布（按荣誉/企业资质/行政许可/高新聚合条数）
    category_rows: List[Dict[str, Any]] = []
    for label, rows, total_src in (
        ("荣誉资质", honor_rows, honor),
        ("企业资质", enterprise_rows, enterprise),
        ("行政许可", license_rows, license_p),
        ("高新技术企业认证", hitech_rows, hitech),
    ):
        n = len(rows)
        t = _safe_total(total_src)
        if t is not None:
            try:
                n = int(t)
            except (TypeError, ValueError):
                n = len(rows)
        if n > 0:
            category_rows.append({"资质类别": label, "数量": str(n)})

    sections = [
        {"key": "cert_profile", "title": "资质证书概况", "kind": "kv"},
        {"key": "category_dist", "title": "资质类别分布", "kind": "pie", "note": "按荣誉/企业资质/行政许可/高新聚合资质条数",
         "chart": {"name": "资质类别", "value": "数量", "donut": True},
         "columns": [("资质类别", "资质类别"), ("数量", "数量")]},
        {"key": "class_cluster", "title": "资质类别聚类", "kind": "donut", "note": "按 qualificationClasses（科技研发与创新类/产业升级与转型类等）聚合",
         "chart": {"name": "资质类别聚类", "value": "数量", "donut": True},
         "columns": [("资质类别聚类", "资质类别聚类"), ("数量", "数量")]},
        {"key": "hitech_industry", "title": "高新技术领域覆盖", "kind": "bar", "note": "按 highTechIndustryList 聚合的高新技术领域覆盖次数",
         "chart": {"name": "高新技术领域", "value": "覆盖次数", "orient": "v"},
         "columns": [("高新技术领域", "高新技术领域"), ("覆盖次数", "覆盖次数")]},
        {"key": "cert_year_trend", "title": "获证年度趋势", "kind": "line", "note": "按 publishYear 统计企业资质获证数量",
         "chart": {"x": "年份", "y": "数量", "area": True},
         "columns": [("年份", "年份"), ("数量", "数量")]},
        {"key": "honor_records", "title": "荣誉资质", "kind": "table", "note": f"共 {_safe_total(honor) or len(honor_rows)} 条，展示前若干条",
         "columns": [("资质类型", "资质类型"), ("资质级别", "资质级别"), ("认定机关", "认定机关"), ("发布日期", "发布日期"), ("有效期", "有效期")]},
        {"key": "enterprise_records", "title": "企业资质", "kind": "table", "note": f"共 {_safe_total(enterprise) or len(enterprise_rows)} 条，展示前 N 条",
         "columns": [("资质类型", "资质类型"), ("资质类别聚类", "资质类别聚类"), ("资质级别", "资质级别"), ("发布单位", "发布单位"), ("发布日期", "发布日期"), ("获证年度", "获证年度")]},
        {"key": "license_records", "title": "行政许可", "kind": "table", "note": f"共 {_safe_total(license_p) or len(license_rows)} 条，展示前 N 条",
         "columns": [("许可事项", "许可事项"), ("许可机关", "许可机关"), ("当前状态", "当前状态"), ("有效期自", "有效期自"), ("有效期至", "有效期至")]},
        {"key": "hitech_records", "title": "高新技术企业认证", "kind": "table", "note": f"共 {_safe_total(hitech) or len(hitech_rows)} 条，展示前 {len(hitech_rows)} 条",
         "columns": [("证书编号", "证书编号"), ("资质类别", "资质类别"), ("发证机构", "发证机构"), ("颁证日期", "颁证日期"), ("截止日期", "截止日期"), ("证书状态", "证书状态")]},
    ]

    return {
        "sections": sections,
        "cert_profile": profile_kv,
        "category_dist": category_rows,
        "class_cluster": class_cluster_rows,
        "hitech_industry": hitech_industry_rows,
        "cert_year_trend": cert_year_rows,
        "honor_records": honor_rows,
        "enterprise_records": enterprise_rows,
        "license_records": license_rows,
        "hitech_records": hitech_rows,
    }


def _build_honor_rows(honor: Any) -> List[Dict[str, Any]]:
    rows = []
    for item in _first_list(honor):
        if not isinstance(item, dict):
            continue
        valid = "、".join([d for d in (_text(item.get("eaqBeginDate")), _text(item.get("eaqEndDate"))) if d]) or "-"
        rows.append({
            "资质类型": _text(item.get("eaqType")) or _text(item.get("eaqTitle")) or "-",
            "资质级别": _text(item.get("eaqRecognitionLevel")) or "-",
            "认定机关": _text(item.get("eaqAuthority")) or "-",
            "发布日期": _text(item.get("eaqPublishDate")) or "-",
            "有效期": valid,
        })
    return rows


def _build_enterprise_rows(enterprise: Any) -> List[Dict[str, Any]]:
    rows = []
    for item in _first_list(enterprise):
        if not isinstance(item, dict):
            continue
        rows.append({
            "资质类型": _text(item.get("qualificationType")) or "-",
            "资质类别聚类": _text(item.get("qualificationClasses")) or "-",
            "资质级别": _text(item.get("qualificationLevel")) or "-",
            "发布单位": _text(item.get("agency")) or "-",
            "发布日期": _text(item.get("publishDate")) or "-",
            "获证年度": _text(item.get("publishYear")) or "-",
        })
    return rows


def _class_cluster_rows(enterprise: Any) -> List[Dict[str, Any]]:
    """资质类别聚类 donut: aggregate qualificationClasses across enterprise quals.

    qualificationClasses e.g. '科技研发与创新类' / '产业升级与转型类'.
    """
    counter: Dict[str, int] = {}
    for item in _first_list(enterprise):
        if not isinstance(item, dict):
            continue
        cls = _text(item.get("qualificationClasses"))
        if cls:
            counter[cls] = counter.get(cls, 0) + 1
    return [{"资质类别聚类": k, "数量": v} for k, v in sorted(counter.items(), key=lambda x: x[1], reverse=True)]


def _hitech_industry_rows(enterprise: Any) -> List[Dict[str, Any]]:
    """高新技术领域覆盖 bar: aggregate highTechIndustryList across enterprise quals.

    Each row's highTechIndustryList is e.g. ['电子信息','航空航天','高技术服务',
    '新能源与节能','先进制造与自动化'].
    """
    counter: Dict[str, int] = {}
    for item in _first_list(enterprise):
        if not isinstance(item, dict):
            continue
        for ind in (item.get("highTechIndustryList") or []):
            ind = _text(ind)
            if ind:
                counter[ind] = counter.get(ind, 0) + 1
    return [{"高新技术领域": k, "覆盖次数": v} for k, v in sorted(counter.items(), key=lambda x: x[1], reverse=True)]


def _cert_year_rows(enterprise: Any) -> List[Dict[str, Any]]:
    """获证年度趋势 line: aggregate publishYear across enterprise quals."""
    counter: Dict[str, int] = {}
    for item in _first_list(enterprise):
        if not isinstance(item, dict):
            continue
        year = item.get("publishYear")
        if year is None:
            continue
        y = _text(year)
        if y and y.isdigit():
            counter[y] = counter.get(y, 0) + 1
    return [{"年份": y, "数量": n} for y, n in sorted(counter.items())]


def _build_license_rows(license_p: Any) -> List[Dict[str, Any]]:
    rows = []
    for item in _first_list(license_p):
        if not isinstance(item, dict):
            continue
        rows.append({
            "许可事项": _text(item.get("fileName")) or _text(item.get("content")) or "-",
            "许可机关": _text(item.get("authority")) or "-",
            "当前状态": _text(item.get("status")) or "-",
            "有效期自": _text(item.get("beginDate")) or "-",
            "有效期至": _text(item.get("endDate")) or "-",
        })
    return rows


def _build_hitech_rows(hitech: Any) -> List[Dict[str, Any]]:
    rows = []
    for item in _first_list(hitech):
        if not isinstance(item, dict):
            continue
        rows.append({
            "证书编号": _text(item.get("certId")) or "-",
            "资质类别": _text(item.get("certType")) or "-",
            "发证机构": _text(item.get("certAuthority")) or "-",
            "颁证日期": _text(item.get("certPublishTime")) or "-",
            "截止日期": _text(item.get("certExpireTime")) or "-",
            "证书状态": _text(item.get("certStatus")) or "-",
        })
    return rows


def build_records(core: Mapping[str, Any]) -> List[Dict[str, Any]]:
    out = []
    for item in core.get("honor_records") or []:
        out.append({
            "资质类型": item.get("资质类型") or "-",
            "资质级别": item.get("资质级别") or "-",
            "认定机关": item.get("认定机关") or "-",
        })
    for item in core.get("hitech_records") or []:
        out.append({
            "资质类型": "高新技术企业认证",
            "资质级别": item.get("资质类别") or "-",
            "认定机关": item.get("发证机构") or "-",
        })
    # de-duplicate-ish cap
    return out[:20]


def build_insights(subject: Mapping[str, Any], core: Mapping[str, Any], metrics: List[Mapping[str, Any]]) -> List[Dict[str, Any]]:
    insights: List[Dict[str, Any]] = []
    metric_map = {m["label"]: str(m["value"]) for m in metrics}
    cert_total = metric_map.get("证书总数")
    recent = metric_map.get("近一年获证")
    hitech_n = metric_map.get("高新技术企业认证")

    if cert_total:
        insights.append({
            "feature": "资质资产规模",
            "evidence": f"企业资质证书总数 {cert_total}。",
            "interpretation": "证书总量反映企业资质积累的广度，是招投标、政策申报与商业合作的重要门槛指标。",
        })
    if recent and cert_total:
        try:
            r = float(recent)
            c = float(cert_total)
            share = r / c * 100 if c else 0
            insights.append({
                "feature": "近期获证活跃度",
                "evidence": f"近一年获证 {recent} 项，占证书总量约 {share:.0f}%。",
                "interpretation": "近期获证占比反映资质扩张节奏：占比高说明企业处于资质快速积累期（如新业务/新政策驱动），占比低则资质结构趋于稳定。",
            })
        except (TypeError, ValueError):
            pass
    if hitech_n and hitech_n != "0":
        insights.append({
            "feature": "高新技术资质",
            "evidence": f"高新技术企业认证记录 {hitech_n} 条。",
            "interpretation": "高新技术企业资质是企业研发能力与税收优惠的重要依据；持续在有效期内说明企业研发投入稳定。",
        })
    category_rows = core.get("category_dist") or []
    if category_rows:
        conc = _concentration(category_rows, "资质类别", "数量", 2)
        if conc:
            insights.append({
                "feature": "资质类别集中度",
                "evidence": f"“{conc['top']}”类资质占比约 {conc['top_share']:.0f}%，前 2 类合计 {conc['cr']:.0f}%（CR2）。",
                "interpretation": "资质类别集中度反映业务聚焦方向：CR2 偏高意味着资质集中于少数类别、专业化方向明确；CR2 偏低则代表业务线多元、跨领域布局。",
            })
    # 高新证书有效性（基于 hitech_records 的证书状态字段）
    hitech_rows = core.get("hitech_records") or []
    if hitech_rows:
        valid = sum(1 for r in hitech_rows if str(r.get("证书状态", "")).strip() in ("有效", "正常", "生效"))
        total_h = len(hitech_rows)
        if total_h:
            insights.append({
                "feature": "高新证书有效性",
                "evidence": f"高新证书 {total_h} 条中有效 {valid} 条（{valid / total_h * 100:.0f}%）。",
                "interpretation": "高新证书有效率直接影响企业享受税收优惠与政策红利的连续性；存在过期记录时建议尽快启动重新认定。",
            })
    cert_profile = core.get("cert_profile") or {}
    cert_types = cert_profile.get("涵盖证书类别")
    if cert_types:
        try:
            n_types = len([t for t in str(cert_types).replace("、", "/").split("/") if t.strip()])
        except Exception:
            n_types = 0
        insights.append({
            "feature": "资质类别覆盖",
            "evidence": f"涵盖证书类别约 {n_types or '多'} 类：{cert_types}。",
            "interpretation": "资质类别越分散，说明企业业务线越多元；类别集中则代表专业化方向明确。",
        })
    # 资质类别聚类集中度（HIGHEST VALUE — qualificationClasses）
    class_rows = core.get("class_cluster") or []
    if class_rows:
        conc = _concentration(class_rows, "资质类别聚类", "数量", 2)
        total_cls = sum(int(r.get("数量", 0) or 0) for r in class_rows)
        if conc:
            insights.append({
                "feature": "资质类别聚类",
                "evidence": f"企业资质按类别聚为 {len(class_rows)} 类，合计 {total_cls} 项；其中“{conc['top']}”占比约 {conc['top_share']:.0f}%，前 2 类合计 {conc['cr']:.0f}%（CR2）。",
                "interpretation": "资质类别聚类反映企业资质的政策定位：科技研发与创新类占比高通常意味着以技术创新为核心驱动；产业升级与转型类则反映传统产能升级方向。",
            })
    # 高新技术领域覆盖
    hitech_ind_rows = core.get("hitech_industry") or []
    if hitech_ind_rows:
        top_field = hitech_ind_rows[0]
        insights.append({
            "feature": "高新技术领域覆盖",
            "evidence": f"覆盖 {len(hitech_ind_rows)} 个高新技术领域（电子信息/航空航天/高技术服务/新能源与节能/先进制造与自动化等），“{top_field.get('高新技术领域', '-')}”覆盖最多（{top_field.get('覆盖次数', 0)} 次）。",
            "interpretation": "高新技术领域覆盖广度反映企业的技术辐射面：覆盖多领域通常意味着跨学科技术整合能力强，是综合型高技术企业的典型特征。",
        })
    # 获证年度趋势
    year_rows = core.get("cert_year_trend") or []
    if year_rows:
        try:
            nums = [(r.get("年份", "-"), int(r.get("数量", 0) or 0)) for r in year_rows]
            peak = max(nums, key=lambda x: x[1]) if nums else ("-", 0)
            insights.append({
                "feature": "获证年度趋势",
                "evidence": f"企业资质获证跨 {len(nums)} 个年度，峰值在“{peak[0]}”（新增 {peak[1]} 项）。",
                "interpretation": "获证年度趋势反映企业资质建设的投入节奏：某年集中爆发通常对应政策窗口期或重大认证批次；近年新增放缓则可能进入资质维护阶段。",
            })
        except (TypeError, ValueError):
            pass
    if not insights:
        insights.append({
            "feature": "数据完整性",
            "evidence": "部分维度未返回有效数据。",
            "interpretation": "建议核对匹配关键词是否为企业全称，或检查 MCP 连接与上游数据产品覆盖范围。",
        })
    return insights


def build_abstract(subject: Mapping[str, Any], core: Mapping[str, Any], metrics: List[Mapping[str, Any]]) -> str:
    name = subject.get("enterprise") or subject.get("match_raw") or "目标企业"
    parts = [f"本报告以“{name}”为分析对象，基于资质公开数据，系统呈现企业资质证书概况、荣誉资质、企业资质、行政许可与高新技术企业认证明细。"]
    if metrics:
        kv = "、".join(f"{m['label']} {m['value']}" for m in metrics[:5])
        parts.append(f"关键指标包括：{kv}。")
    parts.append("报告同时给出资质资产规模、近期获证活跃度与高新技术资质的结构化解读，便于招投标、政策申报与商业合作决策参考。")
    return "".join(parts)


# --------------------------------------------------------------------------- #
# Dry-run sample
# --------------------------------------------------------------------------- #

def build_dry_run_payload(raw: str, keyword_type: str) -> Dict[str, Any]:
    try:
        sample = load_json_file(SAMPLE_PATH)
    except Exception:
        sample = {}
    sample = sample if isinstance(sample, dict) else {}
    subject = sample.get("subject") or {"enterprise": raw, "matchKeyword": raw, "keywordType": keyword_type, "match_raw": raw}
    subject = {**subject, "match_raw": raw, "keywordType": keyword_type}
    core = sample.get("core_analysis") or {}
    metrics = sample.get("metrics") or []
    return _assemble(subject, core, metrics, dry_run=True)


# --------------------------------------------------------------------------- #
# Assembly
# --------------------------------------------------------------------------- #

def _assemble(subject: Mapping[str, Any], core: Mapping[str, Any], metrics: List[Mapping[str, Any]], *, dry_run: bool) -> Dict[str, Any]:
    abstract = build_abstract(subject, core, metrics)
    records = build_records(core)
    insights = build_insights(subject, core, metrics)
    # Quality gate: count populated core-analysis sections.
    ca = core if isinstance(core, dict) else {}
    secs = ca.get("sections", [])
    if secs:
        total_secs = len(secs)
        populated = sum(1 for s in secs if isinstance(s, dict) and ca.get(s.get("key")) not in (None, "", [], {}))
    else:
        total_secs = max(1, len([k for k in ca if k != "sections"]))
        populated = sum(1 for k in ca if k != "sections" and ca.get(k) not in (None, "", [], {}))
    quality_report = {
        "total_sections": total_secs,
        "populated_sections": populated,
        "empty_sections": total_secs - populated,
        "coverage_pct": round(populated / max(1, total_secs) * 100),
    }
    if populated == 0:
        import sys
        print("⚠️ 质量门禁警告: 所有核心分析维度均无数据", file=sys.stderr)
    title = f"{subject.get('enterprise') or '目标企业'} 资质大数据报告"
    return {
        "report_type": REPORT_TYPE,
        "title": title,
        "banner": REPORT_BANNER,
        "subject": dict(subject),
        "abstract": abstract,
        "summary": abstract,
        "executive_summary": [item["interpretation"] for item in insights][:5] or [abstract[:120]],
        "metrics": list(metrics),
        "caliber": build_caliber(subject),
        "core_analysis": dict(core),
        "representative_records": records,
        "insights": insights,
        "data_source": {
            "mcp_server": "qualification-mcp-server",
            "products": [
                {"name": "荣誉资质", "product_id": "66b71b498dd25dbfbe8b0a9f"},
                {"name": "企业资质", "product_id": "67f3b410ac893a1d33dadef5"},
                {"name": "企业模糊查询", "product_id": "675cea1f0e009a9ea37edaa1"},
                {"name": "行政许可", "product_id": "669fb610a32fff27615b0c03"},
                {"name": "资质证书概况", "product_id": "66a24df68912d491d34ab0a1"},
                {"name": "高新技术企业认证", "product_id": "669f8ec259dda752d9799950"},
            ],
            "generated_at": dt.datetime.now().astimezone().isoformat(timespec="seconds"),
            "dry_run": dry_run,
            "quality_report": quality_report,
        },
    }


def build_payload(raw: str, keyword_type: str, page_size: int) -> Dict[str, Any]:
    resolved = resolve_enterprise_name(raw)
    enterprise = resolved["enterprise"]
    mk_args: Dict[str, Any] = {"matchKeyword": enterprise, "keywordType": keyword_type}
    profile = _safe_call(T_PROFILE, mk_args)
    honor = _safe_call(T_HONOR, mk_args)
    enterprise_q = _safe_call(T_ENTERPRISE, {**mk_args, "pageIndex": 1, "pageSize": page_size})
    license_p = _safe_call(T_LICENSE, {**mk_args, "pageIndex": 1, "pageSize": page_size})
    hitech = _safe_call(T_HITECH, {**mk_args, "pageIndex": 1, "pageSize": page_size})

    subject = build_subject(raw, resolved, keyword_type)
    core = build_core_analysis(profile, honor, enterprise_q, license_p, hitech)
    metrics = build_metrics(
        profile if isinstance(profile, dict) else {},
        honor, enterprise_q, license_p, hitech, core,
    )
    _derive_core_metrics(metrics, core if isinstance(core, dict) else {})
    # --- Enterprise profile enrichment (from fuzzy_search) ---
    _enrich_metrics_with_profile(metrics, resolved.get("record") if isinstance(resolved, dict) else None)
    return _assemble(subject, core, metrics, dry_run=False)


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #

def main() -> None:
    parser = argparse.ArgumentParser(description="Compose a qualification big-data report via the qualification MCP.")
    parser.add_argument("--enterprise", required=True, help="企业全称或关键词（关键词将自动模糊补全）")
    parser.add_argument("--keyword-type", default="name", help="主体类型：name/nameId/regNumber/socialCreditCode")
    parser.add_argument("--page-size", type=int, default=10, help="分页大小（最多 50）")
    parser.add_argument("--dry-run", action="store_true", help="不调用真实 MCP，使用样例数据组装报告骨架")
    parser.add_argument("--output", help="输出 JSON 路径；省略则打印到 stdout")
    parser.add_argument("--report-output", help="同时输出 HTML 报告（.html）与 Markdown 报告（.md）")
    parser.add_argument("--pdf-output", help="额外输出 PDF 报告（.pdf）；需要 Playwright + Chromium")
    args = parser.parse_args()

    if args.dry_run:
        payload = build_dry_run_payload(args.enterprise, args.keyword_type)
    else:
        payload = build_payload(args.enterprise, args.keyword_type, args.page_size)

    if args.output:
        out = pathlib.Path(args.output).expanduser()
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json_dumps(payload, pretty=True), encoding="utf-8")
        print_json({"ok": True, "json": str(out), "dry_run": args.dry_run})
    else:
        print_json(payload)

    if args.report_output:
        base_out = pathlib.Path(args.report_output).expanduser()
        base_out.parent.mkdir(parents=True, exist_ok=True)
        html_path = base_out.with_suffix(".html") if base_out.suffix.lower() not in (".html", ".htm") else base_out
        md_path = html_path.with_suffix(".md")
        html_path.write_text(render_html(payload), encoding="utf-8")
        md_path.write_text(render_markdown(payload), encoding="utf-8")
        if args.pdf_output:
            pdf_path = pathlib.Path(args.pdf_output).expanduser()
            pdf_path.parent.mkdir(parents=True, exist_ok=True)
            html_to_pdf(render_html(payload), str(pdf_path))
        print_json({"ok": True, "html": str(html_path), "markdown": str(md_path), "pdf": str(pdf_path) if args.pdf_output else None, "dry_run": args.dry_run})


if __name__ == "__main__":
    main()
