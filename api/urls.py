from django.urls import path
from rest_framework.routers import DefaultRouter
from .views import (
    SupplierViewSet, CustomerViewSet, ProductViewSet, ProductBatchViewSet,
    PurchaseViewSet, SaleViewSet, SaleReturnViewSet,
    InventoryMovementViewSet, ActivityLogViewSet, NotificationViewSet,
    adjust_stock_view, global_search_view, user_profile_view, change_password_view,
    login_view, analytics_view
)

router = DefaultRouter()
router.register(r'suppliers', SupplierViewSet)
router.register(r'customers', CustomerViewSet)
router.register(r'products', ProductViewSet)
router.register(r'batches', ProductBatchViewSet)
router.register(r'purchases', PurchaseViewSet)
router.register(r'sales', SaleViewSet)
router.register(r'returns', SaleReturnViewSet)
router.register(r'movements', InventoryMovementViewSet)
router.register(r'logs', ActivityLogViewSet)
router.register(r'notifications', NotificationViewSet)

urlpatterns = [
    path('login/', login_view),
    path('analytics/', analytics_view),
    path('inventory/adjust/', adjust_stock_view),
    path('search/', global_search_view),
    path('profile/', user_profile_view),
    path('change-password/', change_password_view),
]

urlpatterns += router.urls