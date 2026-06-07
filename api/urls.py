from django.urls import path
from rest_framework.routers import DefaultRouter
from .views import ProductViewSet, SaleViewSet, login_view
from .views import create_default_users


router = DefaultRouter()

router.register(r'products', ProductViewSet)
router.register(r'sales', SaleViewSet)

urlpatterns = [
    path('login/', login_view),
    path('create-users/', create_default_users),
]

urlpatterns += router.urls