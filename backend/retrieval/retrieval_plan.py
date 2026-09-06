"""
Retrieval Plan Đa Nguồn — Mục 3 GĐ1.

Thay cơ chế single-route (1 câu hỏi chỉ đi 1 layer) bằng retrieval plan
cho phép một câu hỏi gọi đồng thời Facts + KG + Docs + Tool API khi cần.

Nguyên tắc:
- IAM phải sẵn sàng trước khi retrieval plan gọi Tool API
- Kết quả từ nhiều nguồn được merge và ranking theo relevance
- Không để LLM tự chọn nguồn; plan dựa trên question_type và routing context

Sơ đồ:
    RetrievalPlan.execute()
        ├── asyncio.gather (song song)
        │   ├── _fetch_facts()        → Layer 1 (nếu question_type có định_lượng)
        │   ├── _fetch_kg()           → Layer 2 (nếu có soil/season/pest/tech)
        │   ├── _fetch_docs()         → Layer 3 RAG (luôn chạy fallback)
        │   └── _fetch_tools()        → NextFarm IoT (nếu có farm_context)
        └── merge_results()           → Hợp nhất, loại trùng, xếp ưu tiên
"""
import asyncio
import logging
from typing import Optional, Any
from dataclasses import dataclass, field

from backend.layers.layer1_facts import get_fact, search_facts_by_topic
from backend.layers.layer2_kg import find_suitable_varieties, find_pest_info, find_technique_info
from backend.layers.layer3_docs import semantic_search, hybrid_search

logger = logging.getLogger(__name__)


@dataclass
class RetrievalSource:
    """Kết quả từ một nguồn dữ liệu."""
    source_name: str          # "facts", "kg", "docs", "tools"
    found: bool
    data: Any                 # dữ liệu thô
    data_text: str            # dữ liệu đã format thành text
    source_info: str          # tên tài liệu/nguồn
    warning: Optional[str] = None       # cảnh báo (stale, partial match...)
    priority: int = 0         # 0=cao nhất, tăng dần


@dataclass
class RetrievalPlanResult:
    """Kết quả tổng hợp từ retrieval plan."""
    found: bool
    sources: list[RetrievalSource] = field(default_factory=list)
    merged_data: str = ""
    merged_source_info: str = ""
    warnings: list[str] = field(default_factory=list)
    primary_layer: str = "none"
    sources_used: list[str] = field(default_factory=list)
    tool_calls: list = field(default_factory=list)
    requires_clarification: bool = False


async def _fetch_facts(
    attribute: str,
    crop: Optional[str],
    season: Optional[str],
    soil_type: Optional[str],
    growth_stage: Optional[str] = None,
) -> RetrievalSource:
    """Fetch từ Layer 1 — Structured Fact Store."""
    try:
        result = await asyncio.to_thread(
            get_fact,
            attribute=attribute,
            crop=crop,
            season=season,
            soil_type=soil_type,
            growth_stage=growth_stage,
        )
        if result["found"]:
            facts_text = "\n".join([
                f"- {r['attribute']}: {r['value']} {r.get('unit', '')} "
                f"({r.get('condition_note', '')})"
                f"{' [v' + r.get('fact_version', '1.0') + ']' if r.get('fact_version') else ''}"
                for r in result["results"]
            ])
            data_text = f"Số liệu từ Fact Store:\n{facts_text}"
            source_info = result["results"][0].get("source_document_id", "Kho tri thức")
            return RetrievalSource(
                source_name="facts",
                found=True,
                data=result["results"],
                data_text=data_text,
                source_info=source_info,
                warning=result.get("warning"),
                priority=0,  # Facts có priority cao nhất (định lượng chính xác)
            )
    except Exception as e:
        logger.error(f"RetrievalPlan _fetch_facts error: {e}")

    return RetrievalSource(
        source_name="facts", found=False, data=[], data_text="", source_info="", priority=0
    )


async def _fetch_kg(
    keywords: list[str],
    soil_type: Optional[str],
    season: Optional[str],
) -> RetrievalSource:
    """Fetch từ Layer 2 — Knowledge Graph."""
    try:
        keyword_str = " ".join(keywords) if keywords else ""

        # Thử pest info
        if keyword_str:
            pest_result = await asyncio.to_thread(find_pest_info, pest_name=keyword_str)
            if pest_result["found"]:
                import json
                return RetrievalSource(
                    source_name="kg",
                    found=True,
                    data=pest_result["results"],
                    data_text=f"Thông tin sâu bệnh từ Knowledge Graph:\n{json.dumps(pest_result['results'], ensure_ascii=False, indent=2)}",
                    source_info=pest_result["source_info"],
                    priority=1,
                )

        # Thử technique info
        if keyword_str:
            tech_result = await asyncio.to_thread(find_technique_info, technique_name=keyword_str)
            if tech_result["found"]:
                import json
                return RetrievalSource(
                    source_name="kg",
                    found=True,
                    data=tech_result["results"],
                    data_text=f"Thông tin kỹ thuật từ Knowledge Graph:\n{json.dumps(tech_result['results'], ensure_ascii=False, indent=2)}",
                    source_info=tech_result["source_info"],
                    priority=1,
                )

        # Thử variety info
        if soil_type or season:
            var_result = await asyncio.to_thread(
                find_suitable_varieties, soil_type=soil_type, season=season
            )
            if var_result["found"]:
                import json
                return RetrievalSource(
                    source_name="kg",
                    found=True,
                    data=var_result["results"],
                    data_text=f"Giống phù hợp từ Knowledge Graph:\n{json.dumps(var_result['results'], ensure_ascii=False, indent=2)}",
                    source_info=var_result["source_info"],
                    priority=1,
                )

    except Exception as e:
        logger.error(f"RetrievalPlan _fetch_kg error: {e}")

    return RetrievalSource(
        source_name="kg", found=False, data=[], data_text="", source_info="", priority=1
    )


async def _fetch_docs(
    query: str,
    crop: Optional[str],
    season: Optional[str],
    top_k: int = 4,
) -> RetrievalSource:
    """Fetch từ Layer 3 — Document Store RAG (Hybrid: Dense + BM25 + RRF).

    GĐ3 Hybrid Retrieval: Học từ RAG-and-Agent — dùng hybrid_search thay vì
    semantic_search đơn thuần. BM25 giúp bắt chính xác tên thuốc BVTV,
    tên giống, mã liều lượng mà embedding dễ bỏ sót.
    Fallback an toàn về dense-only nếu BM25 không khả dụng.
    """
    try:
        # Dùng hybrid_search (Dense + BM25 + RRF) thay vì semantic_search
        result = await asyncio.to_thread(
            hybrid_search, query=query, crop=crop, season=season, top_k=top_k
        )
        if result["found"]:
            chunks_text = "\n\n---\n\n".join([
                f"[Nguồn: {c.get('source', 'Tài liệu')} | Topic: {c.get('topic', 'Nông nghiệp')}]\\n{c['chunk_text']}"
                for c in result["chunks"]
            ])
            retrieval_mode = result.get("retrieval_mode", "unknown")
            return RetrievalSource(
                source_name="docs",
                found=True,
                data=result["chunks"],
                data_text=f"Nội dung từ tài liệu nông nghiệp [{retrieval_mode}]:\n{chunks_text}",
                source_info=result["source_info"],
                priority=2,  # Docs có priority thấp hơn Facts/KG
            )
    except Exception as e:
        logger.error(f"RetrievalPlan _fetch_docs error: {e}")

    return RetrievalSource(
        source_name="docs", found=False, data=[], data_text="", source_info="", priority=2
    )


async def _fetch_tools(
    farm_context: Any,
    farm_id: str,
    zone_id: Optional[str],
    sensor_types: Optional[list[str]] = None,
    device_id: Optional[str] = None,
    question: str = "",
) -> RetrievalSource:
    """Fetch từ NextFarm IoT Tools — chỉ chạy khi có farm_context hợp lệ."""
    if farm_context is None or not farm_id:
        return RetrievalSource(
            source_name="tools", found=False, data={}, data_text="",
            source_info="Không có farm context", priority=0
        )

    try:
        from backend.tools.nextfarm_tools import (
            get_latest_sensor, get_alerts, get_device_status, 
            get_irrigation_schedule, get_irrigation_history, get_command_history
        )

        tool_results = []
        warnings = []
        
        q = question.lower()
        is_device = any(k in q for k in ["thiết bị", "van", "bơm", "hoạt động", "trạng thái"])
        is_irrigation_schedule = any(k in q for k in ["lịch tưới", "kế hoạch tưới"])
        is_irrigation_history = any(k in q for k in ["lịch sử tưới", "đã tưới", "hôm qua", "tuần trước"])
        is_command_history = any(k in q for k in ["lịch sử lệnh", "lệnh điều khiển", "ai đã bật", "ai đã tắt"])
        is_sensor = any(k in q for k in ["cảm biến", "độ ẩm", "nhiệt độ", "ph", "ec"])
        
        # Nếu không rõ là gì, mặc định lấy sensor, hoặc nếu người dùng hỏi rõ về sensor
        if not any([is_device, is_irrigation_schedule, is_irrigation_history, is_command_history]) or is_sensor:
            types_to_fetch = sensor_types or ["soil_moisture", "temperature"]
            for stype in types_to_fetch:
                result = await asyncio.to_thread(
                    get_latest_sensor, farm_context, farm_id, zone_id or "zone_A", stype
                )
                tool_results.append(result)
                if result.get("freshness_warning"):
                    warnings.append(result["freshness_warning"])
                    
        if is_device:
            result = await asyncio.to_thread(get_device_status, farm_context, farm_id, device_id or "valve_A")
            tool_results.append(result)
            
        if is_irrigation_schedule:
            result = await asyncio.to_thread(get_irrigation_schedule, farm_context, farm_id, zone_id or "zone_A")
            tool_results.append(result)
            
        if is_irrigation_history:
            result = await asyncio.to_thread(get_irrigation_history, farm_context, farm_id, zone_id or "zone_A", None, None)
            tool_results.append(result)
            
        if is_command_history:
            result = await asyncio.to_thread(get_command_history, farm_context, farm_id, device_id or "valve_A", 10)
            tool_results.append(result)

        # Lấy alerts
        alert_result = await asyncio.to_thread(
            get_alerts, farm_context, farm_id
        )
        if alert_result.get("found"):
            tool_results.append(alert_result)

        import json
        data_text = f"Dữ liệu thực tế từ NextFarm IoT:\n{json.dumps(tool_results, ensure_ascii=False, indent=2)}"
        combined_warning = "\n".join(warnings) if warnings else None

        return RetrievalSource(
            source_name="tools",
            found=True,
            data=tool_results,
            data_text=data_text,
            source_info=f"NextFarm IoT Service (farm={farm_id})",
            warning=combined_warning,
            priority=0,  # Tool data có priority cao nhất khi có
        )

    except PermissionError as e:
        logger.warning(f"RetrievalPlan _fetch_tools IAM denied: {e}")
        return RetrievalSource(
            source_name="tools", found=False, data={},
            data_text="", source_info="",
            warning=str(e), priority=0
        )
    except Exception as e:
        logger.error(f"RetrievalPlan _fetch_tools error: {e}")
        return RetrievalSource(
            source_name="tools", found=False, data={}, data_text="", source_info="", priority=0
        )


async def execute_retrieval_plan(
    routing: Optional[dict] = None,
    norm_question: Optional[str] = None,
    farm_context: Any = None,
    keywords: Optional[list[str]] = None,
    question_type: Optional[str] = None,
    attribute: Optional[str] = None,
    crop: Optional[str] = None,
    season: Optional[str] = None,
    soil_type: Optional[str] = None,
    growth_stage: Optional[str] = None,
    farm_id: Optional[str] = None,
    zone_id: Optional[str] = None,
    sensor_types: Optional[list[str]] = None,
    top_k_docs: int = 4,
    device_id: Optional[str] = None,
    **kwargs,
) -> RetrievalPlanResult:
    """
    Thực thi retrieval plan đa nguồn song song.
    Hỗ trợ gọi qua routing dict hoặc từng tham số riêng rẽ.
    """
    if routing:
        question_type = question_type or routing.get("question_type", "diễn_giải")
        crop = crop or routing.get("crop")
        season = season or routing.get("season")
        soil_type = soil_type or routing.get("soil_type")
        growth_stage = growth_stage or routing.get("growth_stage")
        if keywords is None:
            keywords = routing.get("topic_keywords", [])
        if not attribute:
            attribute = keywords[0] if keywords else (norm_question or "")

    question_type = question_type or "diễn_giải"
    keywords = keywords or []
    attribute = attribute or (keywords[0] if keywords else (norm_question or ""))

    if farm_context is not None:
        farm_id = farm_id or getattr(farm_context, "farm_id", None)
        zone_id = zone_id or getattr(farm_context, "zone_id", None)

    tasks = []
    task_names = []

    # Luôn fetch docs (fallback)
    # SỬA LỖI (2026-09-07): trước đây ép crop rỗng thành chuỗi trống trước khi
    # gọi — dù vô hại về chức năng (semantic_search coi chuỗi trống như None),
    # vẫn là 1 quy ước không nhất quán, dễ gây nhầm lẫn khi code thay đổi.
    # Giờ truyền thẳng biến crop nguyên trạng (None nếu chưa xác định).
    query_str = norm_question or (" ".join(keywords) if keywords else attribute)
    tasks.append(_fetch_docs(query_str, crop, season, top_k_docs))
    task_names.append("docs")

    # Fetch facts cho câu định lượng
    if question_type == "định_lượng":
        tasks.append(_fetch_facts(attribute, crop, season, soil_type, growth_stage))
        task_names.append("facts")

    # Fetch KG cho câu phù hợp/quan hệ hoặc có pest/technique keywords
    if question_type in ("phù_hợp/quan_hệ", "diễn_giải") or (soil_type or season):
        tasks.append(_fetch_kg(keywords, soil_type, season))
        task_names.append("kg")

    # Fetch tools nếu có farm_context (IoT data)
    if farm_context is not None and farm_id:
        tasks.append(_fetch_tools(farm_context, farm_id, zone_id, sensor_types, device_id, query_str))
        task_names.append("tools")

    # Chạy song song
    raw_results = await asyncio.gather(*tasks, return_exceptions=True)

    # Xử lý kết quả
    sources: list[RetrievalSource] = []
    for name, result in zip(task_names, raw_results):
        if isinstance(result, Exception):
            logger.error(f"RetrievalPlan source '{name}' raised: {result}")
        elif isinstance(result, RetrievalSource):
            sources.append(result)

    # Sắp xếp theo priority (thấp = ưu tiên cao)
    sources.sort(key=lambda s: s.priority)

    # Merge kết quả
    found_sources = [s for s in sources if s.found]
    if not found_sources:
        return RetrievalPlanResult(
            found=False,
            sources=sources,
            sources_used=[],
            tool_calls=[],
            requires_clarification=(question_type == "cần_làm_rõ"),
        )

    # Xác định layer chính
    primary = found_sources[0]
    primary_layer_map = {
        "tools": "NextFarm IoT Tools",
        "facts": "Tầng 1 — Structured Fact Store",
        "kg": "Tầng 2 — Knowledge Graph",
        "docs": "Tầng 3 — Document Store",
    }

    # Ghép data text từ tất cả nguồn found
    all_data_parts = []
    all_sources = []
    all_warnings = []

    for s in found_sources:
        if s.data_text:
            all_data_parts.append(s.data_text)
        if s.source_info:
            all_sources.append(s.source_info)
        if s.warning:
            all_warnings.append(s.warning)

    merged_data = "\n\n" + "="*40 + "\n\n".join(all_data_parts)
    merged_source_info = " | ".join(dict.fromkeys(all_sources))
    sources_used = [s.source_name for s in found_sources]
    tool_calls = [s.data for s in found_sources if s.source_name == "tools"]

    return RetrievalPlanResult(
        found=True,
        sources=sources,
        merged_data=merged_data,
        merged_source_info=merged_source_info,
        warnings=all_warnings,
        primary_layer=primary_layer_map.get(primary.source_name, "unknown"),
        sources_used=sources_used,
        tool_calls=tool_calls,
        requires_clarification=(question_type == "cần_làm_rõ"),
    )