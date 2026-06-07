from django.contrib.auth import authenticate
from rest_framework.decorators import api_view
from rest_framework.response import Response
from rest_framework.authtoken.models import Token
from rest_framework import viewsets
from .models import Product, Sale
from .serializers import ProductSerializer, SaleSerializer
from django.contrib.auth.models import User

@api_view(['GET'])
def create_default_users(request):
    if not User.objects.filter(username='owner').exists():
        User.objects.create_user(
            username='owner',
            password='owner123'
        )

    if not User.objects.filter(username='cashier').exists():
        User.objects.create_user(
            username='cashier',
            password='cashier123'
        )

    return Response({'message': 'Users created'})

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