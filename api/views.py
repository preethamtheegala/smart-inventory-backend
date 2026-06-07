from django.contrib.auth import authenticate
from rest_framework.decorators import api_view
from rest_framework.response import Response
from rest_framework.authtoken.models import Token
from rest_framework import viewsets
from .models import Product, Sale
from .serializers import ProductSerializer, SaleSerializer


class ProductViewSet(viewsets.ModelViewSet):
    queryset = Product.objects.all()
    serializer_class = ProductSerializer


class SaleViewSet(viewsets.ModelViewSet):
    queryset = Sale.objects.all().order_by('-created_at')
    serializer_class = SaleSerializer


@api_view(['POST'])
def login_view(request):
    username = request.data.get('username')
    password = request.data.get('password')

    user = authenticate(
        username=username,
        password=password
    )

    if not user:
        return Response(
            {'error': 'Invalid credentials'},
            status=400
        )

    token, _ = Token.objects.get_or_create(user=user)

    role = 'owner'

    if user.username == 'cashier':
        role = 'cashier'

    return Response({
        'token': token.key,
        'username': user.username,
        'role': role
    })