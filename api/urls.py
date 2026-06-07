from django.urls import path
from rest_framework.routers import DefaultRouter
from .views import ProductViewSet, SaleViewSet, login_view

router = DefaultRouter()

router.register(r'products', ProductViewSet)
router.register(r'sales', SaleViewSet)

urlpatterns = [
    path('login/', login_view),
]

urlpatterns += router.urls