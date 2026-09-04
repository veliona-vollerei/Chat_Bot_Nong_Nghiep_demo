"""
IAM / Farm Authorization — Mục 2 GĐ1.

Nguyên tắc bất biến:
- KHÔNG để LLM tự sinh hoặc suy luận farm_id
- Mọi tool call tới IoT/Operational Tools phải đi qua IAM check
- Cross-farm unauthorized access = 0 trường hợp

Trong PoC: mock farm permission từ file/DB nội bộ.
Production: gọi NextFarm IAM Service để resolve allowed_farm_ids.
"""
import logging
from typing import Optional
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


# ─── Data Models ────────────────────────────────────────────────────────────

@dataclass
class FarmContext:
    """Context farm đã được xác thực cho một request."""
    user_id: str
    username: str
    allowed_farm_ids: list[str]
    customer_id: Optional[str] = None
    role: str = "user"
    farm_id: Optional[str] = None
    zone_id: Optional[str] = None

    def can_access_farm(self, farm_id: str) -> bool:
        """Kiểm tra user có quyền truy cập farm_id này không."""
        if self.role == "admin":
            return True
        return farm_id in self.allowed_farm_ids


@dataclass
class AuthorizationResult:
    """Kết quả kiểm tra quyền."""
    allowed: bool
    reason: str
    farm_id: Optional[str] = None
    user_id: Optional[str] = None


# ─── Mock permission store (PoC) ─────────────────────────────────────────────
# Production: thay bằng call tới NextFarm IAM Service
# Format: { username: [farm_id, ...] }
_MOCK_USER_FARM_PERMISSIONS: dict[str, list[str]] = {
    "admin": ["*"],        # admin có thể truy cập mọi farm
    "demo_user": ["farm_001", "farm_002"],
    "farmer_a": ["farm_001"],
    "farmer_b": ["farm_003", "farm_004"],
}


def resolve_allowed_farm_ids(username: str, user_role: str = "user") -> list[str]:
    """
    Resolve danh sách farm_id mà user được phép truy cập.

    PoC: lấy từ mock store.
    Production: gọi NextFarm IAM API.

    Returns:
        List[str]: danh sách farm_id được phép.
                   ["*"] nếu admin (mọi farm).
                   [] nếu không có quyền nào.
    """
    if user_role == "admin":
        return ["*"]

    farms = _MOCK_USER_FARM_PERMISSIONS.get(username, [])
    logger.debug(f"IAM resolve: user={username} → farms={farms}")
    return farms


def build_farm_context(
    username: str,
    user_id: str,
    user_role: str = "user",
    role: Optional[str] = None,
    farm_id: Optional[str] = None,
    zone_id: Optional[str] = None,
    customer_id: Optional[str] = None,
) -> FarmContext:
    """
    Xây dựng FarmContext đã xác thực cho một request.
    Gọi ở đầu mỗi request cần truy cập IoT tool.
    """
    effective_role = role or user_role
    allowed = resolve_allowed_farm_ids(username, effective_role)
    return FarmContext(
        user_id=user_id,
        username=username,
        allowed_farm_ids=allowed,
        customer_id=customer_id,
        role=effective_role,
        farm_id=farm_id,
        zone_id=zone_id,
    )


def check_farm_access(
    farm_context: FarmContext,
    farm_id: str,
    tool_name: str = "unknown_tool",
) -> AuthorizationResult:
    """
    Kiểm tra quyền truy cập farm trước khi gọi tool.

    Args:
        farm_context: FarmContext đã được resolve
        farm_id: farm muốn truy cập
        tool_name: tên tool đang gọi (cho log)

    Returns:
        AuthorizationResult: allowed=True nếu được phép
    """
    if not farm_id:
        return AuthorizationResult(
            allowed=False,
            reason="farm_id không được để trống — LLM không được tự sinh farm_id",
            farm_id=farm_id,
            user_id=farm_context.user_id,
        )

    if farm_context.role == "admin" or "*" in farm_context.allowed_farm_ids:
        logger.info(
            f"IAM ALLOW (admin): tool={tool_name} farm={farm_id} user={farm_context.username}"
        )
        return AuthorizationResult(
            allowed=True,
            reason="admin có toàn quyền",
            farm_id=farm_id,
            user_id=farm_context.user_id,
        )

    if farm_id in farm_context.allowed_farm_ids:
        logger.info(
            f"IAM ALLOW: tool={tool_name} farm={farm_id} user={farm_context.username}"
        )
        return AuthorizationResult(
            allowed=True,
            reason="user có quyền truy cập farm này",
            farm_id=farm_id,
            user_id=farm_context.user_id,
        )

    # Cross-farm access bị chặn — LOG BẮT BUỘC
    logger.warning(
        f"IAM DENY [CROSS-FARM BLOCKED]: "
        f"tool={tool_name} farm={farm_id} user={farm_context.username} "
        f"allowed_farms={farm_context.allowed_farm_ids}"
    )
    return AuthorizationResult(
        allowed=False,
        reason=f"User '{farm_context.username}' không có quyền truy cập farm '{farm_id}'",
        farm_id=farm_id,
        user_id=farm_context.user_id,
    )


def require_farm_access(
    farm_context: FarmContext,
    farm_id: str,
    tool_name: str = "unknown_tool",
) -> None:
    """
    Giống check_farm_access nhưng raise PermissionError ngay nếu bị từ chối.
    Dùng trong tool adapter để fail-fast.

    Raises:
        PermissionError: nếu không có quyền
    """
    result = check_farm_access(farm_context, farm_id, tool_name)
    if not result.allowed:
        raise PermissionError(
            f"Từ chối truy cập: {result.reason}. "
            f"Vui lòng liên hệ quản trị viên để được cấp quyền."
        )


def register_mock_farm_permission(username: str, farm_ids: list[str]) -> None:
    """
    Đăng ký quyền farm cho user trong mock store (chỉ dùng cho test/PoC).
    Production: dùng NextFarm IAM API.
    """
    _MOCK_USER_FARM_PERMISSIONS[username] = farm_ids
    logger.debug(f"IAM mock: đăng ký {username} → {farm_ids}")
