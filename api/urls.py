from rest_framework.routers import DefaultRouter
from .views import ProductViewSet, SaleViewSet

router = DefaultRouter()

router.register(r'products', ProductViewSet)
router.register(r'sales', SaleViewSet)

urlpatterns = router.urls