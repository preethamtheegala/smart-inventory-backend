from django.contrib.auth import authenticate
from django.contrib.auth.models import User
from django.db import transaction
from django.db.models import Sum, F, DecimalField, Count, ExpressionWrapper, Q
from django.utils import timezone
from datetime import datetime, timedelta, time
from rest_framework.decorators import api_view, permission_classes, action
from rest_framework.response import Response
from rest_framework.authtoken.models import Token
from rest_framework import viewsets, status, permissions
from rest_framework.exceptions import PermissionDenied, ValidationError

from .models import (
    Supplier, Customer, Product, ProductBatch, Purchase,
    Sale, SaleReturn, InventoryMovement, ActivityLog, Notification
)
from .serializers import (
    SupplierSerializer, CustomerSerializer, ProductSerializer, ProductBatchSerializer,
    PurchaseSerializer, SaleSerializer, SaleReturnSerializer,
    InventoryMovementSerializer, ActivityLogSerializer, NotificationSerializer,
    StockAdjustmentSerializer
)


def log_activity(user, action_name, entity, entity_id, description):
    try:
        ActivityLog.objects.create(
            user=user if (user and user.is_authenticated) else None,
            action=action_name,
            entity=entity,
            entity_id=str(entity_id),
            description=description
        )
    except Exception as e:
        print(f"Failed to log activity: {e}")


class IsOwnerOnly(permissions.BasePermission):
    """
    Allows access only to authenticated Owner/Admin users (blocks Cashier).
    """
    def has_permission(self, request, view):
        if not (request.user and request.user.is_authenticated):
            return False
        return request.user.username != 'cashier'


class IsOwnerOrReadOnly(permissions.BasePermission):
    """
    Allows read-only access to all users/cashiers, but write operations only to Owner/Admin.
    """
    def has_permission(self, request, view):
        if request.method in permissions.SAFE_METHODS:
            return True
        if not (request.user and request.user.is_authenticated):
            return False
        return request.user.username != 'cashier'


class SupplierViewSet(viewsets.ModelViewSet):
    queryset = Supplier.objects.all().order_by('-id')
    serializer_class = SupplierSerializer
    permission_classes = [IsOwnerOrReadOnly]


    def get_queryset(self):
        qs = Supplier.objects.all().order_by('-id')
        search = self.request.query_params.get('search')
        status_val = self.request.query_params.get('status')
        if search:
            qs = qs.filter(name__icontains=search) | qs.filter(company_name__icontains=search) | qs.filter(phone__icontains=search)
        if status_val and status_val.lower() != 'all':
            qs = qs.filter(status__iexact=status_val)
        return qs

    def perform_create(self, serializer):
        if self.request.user.is_authenticated and self.request.user.username == 'cashier':
            raise PermissionDenied("Cashiers cannot create suppliers.")
        supplier = serializer.save()
        log_activity(self.request.user, 'CREATE', 'Supplier', supplier.id, f"Created supplier '{supplier.name}'")

    def perform_update(self, serializer):
        if self.request.user.is_authenticated and self.request.user.username == 'cashier':
            raise PermissionDenied("Cashiers cannot edit suppliers.")
        supplier = serializer.save()
        log_activity(self.request.user, 'UPDATE', 'Supplier', supplier.id, f"Updated supplier '{supplier.name}'")

    def perform_destroy(self, instance):
        if self.request.user.is_authenticated and self.request.user.username == 'cashier':
            raise PermissionDenied("Cashiers cannot delete suppliers.")
        log_activity(self.request.user, 'DELETE', 'Supplier', instance.id, f"Deleted supplier '{instance.name}'")
        instance.delete()


class CustomerViewSet(viewsets.ModelViewSet):
    queryset = Customer.objects.all().order_by('-id')
    serializer_class = CustomerSerializer

    def get_queryset(self):
        qs = Customer.objects.all().order_by('-id')
        search = self.request.query_params.get('search')
        if search:
            qs = qs.filter(name__icontains=search) | qs.filter(phone__icontains=search) | qs.filter(email__icontains=search)
        return qs

    def perform_create(self, serializer):
        customer = serializer.save()
        log_activity(self.request.user, 'CREATE', 'Customer', customer.id, f"Created customer '{customer.name}'")

    def perform_update(self, serializer):
        customer = serializer.save()
        log_activity(self.request.user, 'UPDATE', 'Customer', customer.id, f"Updated customer '{customer.name}'")

    def perform_destroy(self, instance):
        if self.request.user.is_authenticated and self.request.user.username == 'cashier':
            raise PermissionDenied("Cashiers cannot delete customers.")
        log_activity(self.request.user, 'DELETE', 'Customer', instance.id, f"Deleted customer '{instance.name}'")
        instance.delete()


class ProductBatchViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = ProductBatch.objects.all().order_by('expiry_date')
    serializer_class = ProductBatchSerializer

    def get_queryset(self):
        qs = ProductBatch.objects.all().order_by('expiry_date')
        product_id = self.request.query_params.get('product')
        status_val = self.request.query_params.get('status')
        today = timezone.now().date()

        if product_id:
            qs = qs.filter(product_id=product_id)

        if status_val == 'expiring_soon':
            qs = qs.filter(expiry_date__gte=today, expiry_date__lte=today + timedelta(days=30))
        elif status_val == 'expired':
            qs = qs.filter(expiry_date__lt=today)

        return qs


class ProductViewSet(viewsets.ModelViewSet):
    queryset = Product.objects.all().order_by('-id')
    serializer_class = ProductSerializer
    permission_classes = [IsOwnerOrReadOnly]

    def get_queryset(self):
        qs = Product.objects.all().order_by('-id')
        search = self.request.query_params.get('search')
        category = self.request.query_params.get('category')
        low_stock = self.request.query_params.get('low_stock')
        out_of_stock = self.request.query_params.get('out_of_stock')
        supplier_id = self.request.query_params.get('supplier')

        if search:
            qs = qs.filter(name__icontains=search) | qs.filter(category__icontains=search) | qs.filter(sku__icontains=search)
        if category and category.lower() != 'all':
            qs = qs.filter(category__iexact=category)
        if supplier_id:
            qs = qs.filter(supplier_id=supplier_id)
        if low_stock and low_stock.lower() in ['true', '1', 'yes']:
            qs = qs.filter(quantity__lt=F('min_stock_threshold'))
        if out_of_stock and out_of_stock.lower() in ['true', '1', 'yes']:
            qs = qs.filter(quantity__lte=0)

        return qs

    def perform_create(self, serializer):
        if self.request.user.is_authenticated and self.request.user.username == 'cashier':
            raise PermissionDenied("Cashiers do not have permission to add products.")
        product = serializer.save()
        log_activity(self.request.user, 'CREATE', 'Product', product.id, f"Created product '{product.name}' with initial stock {product.quantity}")

    def perform_update(self, serializer):
        if self.request.user.is_authenticated and self.request.user.username == 'cashier':
            raise PermissionDenied("Cashiers do not have permission to edit products.")
        product = serializer.save()
        log_activity(self.request.user, 'UPDATE', 'Product', product.id, f"Updated product '{product.name}'")

    def perform_destroy(self, instance):
        if self.request.user.is_authenticated and self.request.user.username == 'cashier':
            raise PermissionDenied("Cashiers do not have permission to delete products.")
        log_activity(self.request.user, 'DELETE', 'Product', instance.id, f"Deleted product '{instance.name}'")
        instance.delete()


class PurchaseViewSet(viewsets.ModelViewSet):
    queryset = Purchase.objects.all().order_by('-purchase_date', '-created_at')
    serializer_class = PurchaseSerializer
    permission_classes = [IsOwnerOnly]

    def get_queryset(self):
        qs = Purchase.objects.all().order_by('-purchase_date', '-created_at')
        supplier_id = self.request.query_params.get('supplier')
        product_id = self.request.query_params.get('product')
        search = self.request.query_params.get('search')
        start_date = self.request.query_params.get('start_date')
        end_date = self.request.query_params.get('end_date')

        if supplier_id:
            qs = qs.filter(supplier_id=supplier_id)
        if product_id:
            qs = qs.filter(product_id=product_id)
        if search:
            qs = qs.filter(product__name__icontains=search) | qs.filter(supplier__name__icontains=search) | qs.filter(invoice_no__icontains=search)
        if start_date:
            qs = qs.filter(purchase_date__date__gte=start_date)
        if end_date:
            qs = qs.filter(purchase_date__date__lte=end_date)

        return qs

    def perform_create(self, serializer):
        if self.request.user.is_authenticated and self.request.user.username == 'cashier':
            raise PermissionDenied("Cashiers cannot record purchases.")

        with transaction.atomic():
            purchase = serializer.save(created_by=self.request.user if self.request.user.is_authenticated else None)

            # Atomic product stock update
            product = Product.objects.select_for_update().get(id=purchase.product_id)
            prev_qty = product.quantity
            new_qty = prev_qty + purchase.quantity
            product.quantity = new_qty
            product.cost_price = purchase.cost_price # Update latest unit cost
            if purchase.supplier_id:
                product.supplier = purchase.supplier
            product.save()

            # Create batch if batch number provided
            if purchase.batch_number:
                ProductBatch.objects.create(
                    product=product,
                    batch_number=purchase.batch_number,
                    expiry_date=purchase.expiry_date,
                    quantity=purchase.quantity,
                    purchase_price=purchase.cost_price,
                    supplier=purchase.supplier
                )

            # Record Inventory Movement
            InventoryMovement.objects.create(
                product=product,
                movement_type='PURCHASE',
                previous_quantity=prev_qty,
                new_quantity=new_qty,
                quantity_changed=purchase.quantity,
                reason=f"Stock-in from Purchase PO #{purchase.id} (Supplier: {purchase.supplier.name})",
                reference_id=f"PO #{purchase.id}",
                user=self.request.user if self.request.user.is_authenticated else None
            )

            log_activity(self.request.user, 'CREATE', 'Purchase', purchase.id, f"Recorded purchase of {purchase.quantity} units of '{product.name}' (Total: ₹{purchase.total_cost})")


class SaleViewSet(viewsets.ModelViewSet):
    queryset = Sale.objects.all().order_by('-created_at')
    serializer_class = SaleSerializer

    def get_permissions(self):
        if self.action in ['destroy']:
            return [IsOwnerOnly()]
        return super().get_permissions()


    def get_queryset(self):
        qs = Sale.objects.all().order_by('-created_at')
        search = self.request.query_params.get('search')
        customer_id = self.request.query_params.get('customer')
        date_str = self.request.query_params.get('date')
        start_date = self.request.query_params.get('start_date')
        end_date = self.request.query_params.get('end_date')
        product_id = self.request.query_params.get('product')

        if search:
            qs = qs.filter(product__name__icontains=search) | qs.filter(product__category__icontains=search) | qs.filter(customer__name__icontains=search)
        if customer_id:
            qs = qs.filter(customer_id=customer_id)
        if date_str:
            qs = qs.filter(created_at__date=date_str)
        if start_date:
            qs = qs.filter(created_at__date__gte=start_date)
        if end_date:
            qs = qs.filter(created_at__date__lte=end_date)
        if product_id:
            qs = qs.filter(product_id=product_id)

        return qs

    def perform_create(self, serializer):
        with transaction.atomic():
            product_id = serializer.validated_data['product'].id
            quantity = serializer.validated_data['quantity']

            # Lock product row
            product = Product.objects.select_for_update().get(id=product_id)

            if product.quantity < quantity:
                raise ValidationError({
                    'quantity': f"Insufficient stock. Only {product.quantity} unit(s) available for '{product.name}'."
                })

            prev_qty = product.quantity
            new_qty = prev_qty - quantity
            product.quantity = new_qty
            product.save()

            sale = serializer.save(
                cost_price=product.cost_price,
                created_by=self.request.user if self.request.user.is_authenticated else None
            )

            # Record Inventory Movement
            InventoryMovement.objects.create(
                product=product,
                movement_type='SALE',
                previous_quantity=prev_qty,
                new_quantity=new_qty,
                quantity_changed=-quantity,
                reason=f"Point-of-Sale Checkout Order #{sale.id}",
                reference_id=f"Sale #{sale.id}",
                user=self.request.user if self.request.user.is_authenticated else None
            )

            # Check low stock notification
            if product.quantity <= 0:
                Notification.objects.create(
                    title=f"Out of Stock: {product.name}",
                    message=f"Product '{product.name}' has reached 0 units after Sale #{sale.id}.",
                    notification_type='out_of_stock'
                )
            elif product.quantity < product.min_stock_threshold:
                Notification.objects.create(
                    title=f"Low Stock Alert: {product.name}",
                    message=f"Product '{product.name}' is below minimum threshold ({product.quantity}/{product.min_stock_threshold} units).",
                    notification_type='low_stock'
                )

            log_activity(self.request.user, 'CREATE', 'Sale', sale.id, f"Completed Sale #{sale.id} for {quantity} units of '{product.name}' (Total: ₹{sale.total})")

    def perform_destroy(self, instance):
        if self.request.user.is_authenticated and self.request.user.username == 'cashier':
            raise PermissionDenied("Cashiers do not have permission to delete sales records.")

        with transaction.atomic():
            try:
                product = Product.objects.select_for_update().get(id=instance.product_id)
                prev_qty = product.quantity
                new_qty = prev_qty + instance.quantity
                product.quantity = new_qty
                product.save()

                InventoryMovement.objects.create(
                    product=product,
                    movement_type='MANUAL_ADJUSTMENT',
                    previous_quantity=prev_qty,
                    new_quantity=new_qty,
                    quantity_changed=instance.quantity,
                    reason=f"Sale #{instance.id} record cancelled and deleted by {self.request.user.username if self.request.user.is_authenticated else 'Admin'}",
                    reference_id=f"Sale #{instance.id}",
                    user=self.request.user if self.request.user.is_authenticated else None
                )
            except Product.DoesNotExist:
                pass

            log_activity(self.request.user, 'DELETE', 'Sale', instance.id, f"Deleted Sale #{instance.id} and restored {instance.quantity} units to inventory.")
            instance.delete()


class SaleReturnViewSet(viewsets.ModelViewSet):
    queryset = SaleReturn.objects.all().order_by('-created_at')
    serializer_class = SaleReturnSerializer

    def get_queryset(self):
        qs = SaleReturn.objects.all().order_by('-created_at')
        sale_id = self.request.query_params.get('sale')
        product_id = self.request.query_params.get('product')
        if sale_id:
            qs = qs.filter(sale_id=sale_id)
        if product_id:
            qs = qs.filter(product_id=product_id)
        return qs

    def perform_create(self, serializer):
        with transaction.atomic():
            return_obj = serializer.save(created_by=self.request.user if self.request.user.is_authenticated else None)
            sale = return_obj.sale

            # Restore product stock
            product = Product.objects.select_for_update().get(id=return_obj.product_id)
            prev_qty = product.quantity
            new_qty = prev_qty + return_obj.quantity
            product.quantity = new_qty
            product.save()

            # Update sale status
            total_returned = sum(r.quantity for r in sale.returns.all())
            if total_returned >= sale.quantity:
                sale.status = 'returned'
            else:
                sale.status = 'partially_returned'
            sale.save()

            # Record Inventory Movement
            InventoryMovement.objects.create(
                product=product,
                movement_type='SALE_RETURN',
                previous_quantity=prev_qty,
                new_quantity=new_qty,
                quantity_changed=return_obj.quantity,
                reason=f"Sales Return #{return_obj.id} for Order #{sale.id}: {return_obj.reason}",
                reference_id=f"Return #{return_obj.id}",
                user=self.request.user if self.request.user.is_authenticated else None
            )

            log_activity(self.request.user, 'RETURN', 'SaleReturn', return_obj.id, f"Processed Return #{return_obj.id} for {return_obj.quantity} pcs of '{product.name}' (Refund: ₹{return_obj.refund_amount})")


@api_view(['POST'])
def adjust_stock_view(request):
    """
    Owner-only manual stock adjustment endpoint.
    """
    if request.user.is_authenticated and request.user.username == 'cashier':
        raise PermissionDenied("Cashiers do not have permission to manually adjust inventory stock.")

    serializer = StockAdjustmentSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)

    product_id = serializer.validated_data['product_id']
    adjustment_type = serializer.validated_data['adjustment_type']
    quantity = serializer.validated_data['quantity']
    reason = serializer.validated_data['reason']

    with transaction.atomic():
        try:
            product = Product.objects.select_for_update().get(id=product_id)
        except Product.DoesNotExist:
            return Response({'error': 'Product not found.'}, status=status.HTTP_404_NOT_FOUND)

        prev_qty = product.quantity

        if adjustment_type == 'INCREASE':
            new_qty = prev_qty + quantity
            changed = quantity
        elif adjustment_type == 'DECREASE':
            new_qty = max(0, prev_qty - quantity)
            changed = -(prev_qty - new_qty)
        else: # SET
            new_qty = quantity
            changed = new_qty - prev_qty

        product.quantity = new_qty
        product.save()

        # Audit movement
        movement = InventoryMovement.objects.create(
            product=product,
            movement_type='MANUAL_ADJUSTMENT',
            previous_quantity=prev_qty,
            new_quantity=new_qty,
            quantity_changed=changed,
            reason=reason,
            reference_id="MANUAL",
            user=request.user if request.user.is_authenticated else None
        )

        log_activity(request.user, 'ADJUST', 'Product', product.id, f"Adjusted stock for '{product.name}': {prev_qty} -> {new_qty} ({changed:+d}). Reason: {reason}")

        return Response({
            'success': True,
            'product_id': product.id,
            'product_name': product.name,
            'previous_quantity': prev_qty,
            'new_quantity': new_qty,
            'quantity_changed': changed,
            'movement_id': movement.id
        })


class InventoryMovementViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = InventoryMovement.objects.all().order_by('-created_at')
    serializer_class = InventoryMovementSerializer

    def get_queryset(self):
        qs = InventoryMovement.objects.all().order_by('-created_at')
        product_id = self.request.query_params.get('product')
        movement_type = self.request.query_params.get('type')
        start_date = self.request.query_params.get('start_date')
        end_date = self.request.query_params.get('end_date')
        search = self.request.query_params.get('search')

        if product_id:
            qs = qs.filter(product_id=product_id)
        if movement_type and movement_type.upper() != 'ALL':
            qs = qs.filter(movement_type__iexact=movement_type)
        if start_date:
            qs = qs.filter(created_at__date__gte=start_date)
        if end_date:
            qs = qs.filter(created_at__date__lte=end_date)
        if search:
            qs = qs.filter(product__name__icontains=search) | qs.filter(reason__icontains=search) | qs.filter(reference_id__icontains=search)

        return qs


class ActivityLogViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = ActivityLog.objects.all().order_by('-created_at')
    serializer_class = ActivityLogSerializer
    permission_classes = [IsOwnerOnly]


    def get_queryset(self):
        if self.request.user.is_authenticated and self.request.user.username == 'cashier':
            raise PermissionDenied("Cashiers do not have access to activity audit logs.")

        qs = ActivityLog.objects.all().order_by('-created_at')
        action_val = self.request.query_params.get('action')
        entity_val = self.request.query_params.get('entity')
        search = self.request.query_params.get('search')
        start_date = self.request.query_params.get('start_date')
        end_date = self.request.query_params.get('end_date')

        if action_val and action_val.upper() != 'ALL':
            qs = qs.filter(action__iexact=action_val)
        if entity_val and entity_val.upper() != 'ALL':
            qs = qs.filter(entity__iexact=entity_val)
        if start_date:
            qs = qs.filter(created_at__date__gte=start_date)
        if end_date:
            qs = qs.filter(created_at__date__lte=end_date)
        if search:
            qs = qs.filter(description__icontains=search) | qs.filter(user__username__icontains=search) | qs.filter(entity_id=search) | qs.filter(entity__icontains=search)

        return qs


class NotificationViewSet(viewsets.ModelViewSet):
    queryset = Notification.objects.all().order_by('-created_at')
    serializer_class = NotificationSerializer

    def get_queryset(self):
        qs = Notification.objects.all().order_by('-created_at')
        unread_only = self.request.query_params.get('unread')
        if unread_only and unread_only.lower() in ['true', '1']:
            qs = qs.filter(is_read=False)
        return qs

    @action(detail=False, methods=['POST'])
    def mark_all_read(self, request):
        Notification.objects.filter(is_read=False).update(is_read=True)
        return Response({'success': True, 'message': 'All notifications marked as read.'})

    @action(detail=True, methods=['POST'])
    def mark_read(self, request, pk=None):
        notif = self.get_object()
        notif.is_read = True
        notif.save()
        return Response({'success': True, 'notification_id': notif.id})


@api_view(['GET'])
def global_search_view(request):
    query = request.query_params.get('q', '').strip()
    if not query:
        return Response({
            'products': [],
            'sales': [],
            'suppliers': [],
            'customers': [],
            'purchases': []
        })

    is_owner = True
    if request.user.is_authenticated and request.user.username == 'cashier':
        is_owner = False

    products_qs = Product.objects.filter(Q(name__icontains=query) | Q(category__icontains=query) | Q(sku__icontains=query))[:5]
    sales_qs = Sale.objects.filter(Q(product__name__icontains=query) | Q(customer__name__icontains=query) | Q(id__icontains=query))[:5]
    customers_qs = Customer.objects.filter(Q(name__icontains=query) | Q(phone__icontains=query) | Q(email__icontains=query))[:5]

    suppliers_data = []
    purchases_data = []

    if is_owner:
        suppliers_qs = Supplier.objects.filter(Q(name__icontains=query) | Q(company_name__icontains=query) | Q(phone__icontains=query))[:5]
        purchases_qs = Purchase.objects.filter(Q(product__name__icontains=query) | Q(supplier__name__icontains=query) | Q(invoice_no__icontains=query))[:5]
        suppliers_data = SupplierSerializer(suppliers_qs, many=True).data
        purchases_data = PurchaseSerializer(purchases_qs, many=True).data

    return Response({
        'products': ProductSerializer(products_qs, many=True).data,
        'sales': SaleSerializer(sales_qs, many=True).data,
        'customers': CustomerSerializer(customers_qs, many=True).data,
        'suppliers': suppliers_data,
        'purchases': purchases_data
    })


@api_view(['GET'])
def user_profile_view(request):
    user = request.user
    if not user.is_authenticated:
        return Response({'error': 'Authentication required'}, status=status.HTTP_401_UNAUTHORIZED)

    role = 'owner'
    if user.username == 'cashier':
        role = 'cashier'

    return Response({
        'id': user.id,
        'username': user.username,
        'email': user.email,
        'role': role,
        'first_name': user.first_name,
        'last_name': user.last_name,
        'date_joined': user.date_joined,
        'last_login': user.last_login
    })


@api_view(['POST'])
def change_password_view(request):
    user = request.user
    if not user.is_authenticated:
        return Response({'error': 'Authentication required'}, status=status.HTTP_401_UNAUTHORIZED)

    old_password = request.data.get('old_password', '')
    new_password = request.data.get('new_password', '')

    if not old_password or not new_password:
        return Response({'error': 'Both old and new password are required.'}, status=status.HTTP_400_BAD_REQUEST)

    if len(new_password) < 6:
        return Response({'error': 'New password must be at least 6 characters.'}, status=status.HTTP_400_BAD_REQUEST)

    if not user.check_password(old_password):
        return Response({'error': 'Incorrect current password.'}, status=status.HTTP_400_BAD_REQUEST)

    user.set_password(new_password)
    user.save()

    # Re-issue token
    Token.objects.filter(user=user).delete()
    token = Token.objects.create(user=user)

    log_activity(user, 'UPDATE', 'User', user.id, f"User '{user.username}' changed their password.")

    return Response({'success': True, 'message': 'Password updated successfully.', 'token': token.key})


@api_view(['GET'])
def analytics_view(request):
    """
    Advanced Business Analytics & Profit/Loss with dynamic date range aggregation.
    """
    range_type = request.query_params.get('range', '7days').lower()
    start_date_str = request.query_params.get('start_date')
    end_date_str = request.query_params.get('end_date')

    today = timezone.now().date()

    if range_type == 'today':
        start_date = today
        end_date = today
    elif range_type == 'yesterday':
        start_date = today - timedelta(days=1)
        end_date = today - timedelta(days=1)
    elif range_type == '7days':
        start_date = today - timedelta(days=6)
        end_date = today
    elif range_type == '30days':
        start_date = today - timedelta(days=29)
        end_date = today
    elif range_type == 'this_month':
        start_date = today.replace(day=1)
        end_date = today
    elif range_type == 'prev_month':
        first_this_month = today.replace(day=1)
        last_prev_month = first_this_month - timedelta(days=1)
        start_date = last_prev_month.replace(day=1)
        end_date = last_prev_month
    elif range_type == 'custom' and start_date_str and end_date_str:
        try:
            start_date = datetime.strptime(start_date_str, '%Y-%m-%d').date()
            end_date = datetime.strptime(end_date_str, '%Y-%m-%d').date()
        except:
            start_date = today - timedelta(days=6)
            end_date = today
    else:
        start_date = today - timedelta(days=6)
        end_date = today

    # Catalog KPIs
    total_products = Product.objects.count()
    total_stock = Product.objects.aggregate(total=Sum('quantity'))['total'] or 0

    stock_val_agg = Product.objects.aggregate(
        total_val=Sum(ExpressionWrapper(F('price') * F('quantity'), output_field=DecimalField(max_digits=12, decimal_places=2))),
        total_cost=Sum(ExpressionWrapper(F('cost_price') * F('quantity'), output_field=DecimalField(max_digits=12, decimal_places=2)))
    )
    total_stock_value = stock_val_agg['total_val'] or 0
    total_cost_value = stock_val_agg['total_cost'] or 0

    # Low Stock & Expiring Counts
    low_stock_qs = Product.objects.filter(quantity__lt=F('min_stock_threshold')).order_by('quantity')
    low_stock_count = low_stock_qs.count()
    out_of_stock_count = Product.objects.filter(quantity__lte=0).count()

    expiring_batches_qs = ProductBatch.objects.filter(expiry_date__gte=today, expiry_date__lte=today + timedelta(days=30))
    expiring_batches_count = expiring_batches_qs.count()

    # Sales in selected date range
    sales_qs = Sale.objects.filter(created_at__date__gte=start_date, created_at__date__lte=end_date)
    total_sales_count = sales_qs.count()
    total_units_sold = sales_qs.aggregate(total=Sum('quantity'))['total'] or 0

    sales_revenue = sales_qs.aggregate(total=Sum('total'))['total'] or 0
    sales_cogs = sales_qs.aggregate(
        total=Sum(ExpressionWrapper(F('cost_price') * F('quantity'), output_field=DecimalField(max_digits=12, decimal_places=2)))
    )['total'] or 0

    total_discounts = sales_qs.aggregate(total=Sum('discount_amount'))['total'] or 0
    total_taxes = sales_qs.aggregate(total=Sum('tax_amount'))['total'] or 0

    # Returns in date range
    returns_qs = SaleReturn.objects.filter(created_at__date__gte=start_date, created_at__date__lte=end_date)
    total_returns_amount = returns_qs.aggregate(total=Sum('refund_amount'))['total'] or 0
    total_returned_units = returns_qs.aggregate(total=Sum('quantity'))['total'] or 0

    net_revenue = sales_revenue - total_returns_amount
    gross_profit = net_revenue - sales_cogs
    gross_margin_percent = float((gross_profit / net_revenue * 100)) if net_revenue > 0 else 0.0
    avg_order_value = float(sales_revenue / total_sales_count) if total_sales_count > 0 else 0.0

    # Today's standalone metrics
    today_sales_qs = Sale.objects.filter(created_at__date=today)
    today_sales_count = today_sales_qs.count()
    today_revenue = today_sales_qs.aggregate(total=Sum('total'))['total'] or 0

    # Best Selling Products in Range
    best_sellers_qs = (
        sales_qs.values('product__id', 'product__name', 'product__category')
        .annotate(
            total_quantity_sold=Sum('quantity'),
            total_revenue_generated=Sum('total')
        )
        .order_by('-total_quantity_sold')[:5]
    )

    best_selling_products = [
        {
            'product_id': item['product__id'],
            'product_name': item['product__name'] or 'Unknown',
            'category': item['product__category'] or 'Uncategorized',
            'quantity_sold': item['total_quantity_sold'],
            'revenue': float(item['total_revenue_generated'] or 0)
        }
        for item in best_sellers_qs
    ]

    # Top Profitable Products in Range
    profitable_qs = (
        sales_qs.values('product__id', 'product__name', 'product__category')
        .annotate(
            total_rev=Sum('total'),
            total_cogs=Sum(ExpressionWrapper(F('cost_price') * F('quantity'), output_field=DecimalField(max_digits=12, decimal_places=2)))
        )
        .annotate(
            profit=ExpressionWrapper(F('total_rev') - F('total_cogs'), output_field=DecimalField(max_digits=12, decimal_places=2))
        )
        .order_by('-profit')[:5]
    )

    top_profitable_products = [
        {
            'product_id': item['product__id'],
            'product_name': item['product__name'] or 'Unknown',
            'category': item['product__category'] or 'Uncategorized',
            'revenue': float(item['total_rev'] or 0),
            'cogs': float(item['total_cogs'] or 0),
            'profit': float(item['profit'] or 0)
        }
        for item in profitable_qs
    ]

    # Category Profitability
    cat_profit_qs = (
        sales_qs.values('product__category')
        .annotate(
            total_rev=Sum('total'),
            total_cogs=Sum(ExpressionWrapper(F('cost_price') * F('quantity'), output_field=DecimalField(max_digits=12, decimal_places=2))),
            units_sold=Sum('quantity')
        )
        .annotate(
            profit=ExpressionWrapper(F('total_rev') - F('total_cogs'), output_field=DecimalField(max_digits=12, decimal_places=2))
        )
        .order_by('-total_rev')
    )

    category_profitability = [
        {
            'category': item['product__category'] or 'General',
            'revenue': float(item['total_rev'] or 0),
            'cogs': float(item['total_cogs'] or 0),
            'profit': float(item['profit'] or 0),
            'units_sold': item['units_sold'] or 0,
            'margin_percent': float((item['profit'] / item['total_rev'] * 100)) if (item['total_rev'] and item['total_rev'] > 0) else 0.0
        }
        for item in cat_profit_qs
    ]

    # Category Inventory Distribution
    category_qs = (
        Product.objects.values('category')
        .annotate(
            product_count=Count('id'),
            total_quantity=Sum('quantity'),
            total_value=Sum(ExpressionWrapper(F('price') * F('quantity'), output_field=DecimalField(max_digits=12, decimal_places=2)))
        )
        .order_by('-total_quantity')
    )

    category_breakdown = [
        {
            'category': item['category'] or 'General',
            'product_count': item['product_count'],
            'total_quantity': item['total_quantity'] or 0,
            'total_value': float(item['total_value'] or 0)
        }
        for item in category_qs
    ]

    # Daily Timeline for Selected Range (or last 7-14 days)
    delta_days = (end_date - start_date).days
    timeline_days = min(max(delta_days + 1, 1), 31)

    daily_sales = []
    for i in range(timeline_days):
        curr_day = start_date + timedelta(days=i)
        if curr_day > end_date:
            break
        day_sales_qs = Sale.objects.filter(created_at__date=curr_day)
        day_rev = day_sales_qs.aggregate(total=Sum('total'))['total'] or 0
        day_cogs = day_sales_qs.aggregate(total=Sum(ExpressionWrapper(F('cost_price') * F('quantity'), output_field=DecimalField(max_digits=12, decimal_places=2))))['total'] or 0
        day_count = day_sales_qs.count()

        daily_sales.append({
            'date': curr_day.strftime('%Y-%m-%d'),
            'display_date': curr_day.strftime('%b %d'),
            'revenue': float(day_rev),
            'cogs': float(day_cogs),
            'profit': float(day_rev - day_cogs),
            'sales_count': day_count
        })

    return Response({
        'range': range_type,
        'start_date': start_date.strftime('%Y-%m-%d'),
        'end_date': end_date.strftime('%Y-%m-%d'),
        # Catalog metrics
        'total_products': total_products,
        'total_stock': total_stock,
        'total_stock_value': float(total_stock_value),
        'total_cost_value': float(total_cost_value),
        'low_stock_count': low_stock_count,
        'out_of_stock_count': out_of_stock_count,
        'expiring_batches_count': expiring_batches_count,
        # Sales & Financials for range
        'total_sales_count': total_sales_count,
        'total_units_sold': total_units_sold,
        'total_revenue': float(sales_revenue),
        'total_cogs': float(sales_cogs),
        'gross_profit': float(gross_profit),
        'gross_margin_percent': round(gross_margin_percent, 2),
        'total_discounts': float(total_discounts),
        'total_taxes': float(total_taxes),
        'total_returns_amount': float(total_returns_amount),
        'total_returned_units': total_returned_units,
        'net_revenue': float(net_revenue),
        'avg_order_value': round(avg_order_value, 2),
        # Standalone today
        'today_sales_count': today_sales_count,
        'today_revenue': float(today_revenue),
        # Detailed Lists
        'low_stock_products': ProductSerializer(low_stock_qs[:10], many=True).data,
        'best_selling_products': best_selling_products,
        'top_profitable_products': top_profitable_products,
        'category_profitability': category_profitability,
        'category_breakdown': category_breakdown,
        'daily_sales': daily_sales
    })


@api_view(['POST'])
def login_view(request):
    username = request.data.get('username', '').strip()
    password = request.data.get('password', '').strip()

    user = authenticate(
        username=username,
        password=password
    )

    if not user:
        return Response(
            {'error': 'Invalid credentials. Please check your username and password.'},
            status=status.HTTP_400_BAD_REQUEST
        )

    token, _ = Token.objects.get_or_create(user=user)

    role = 'owner'
    if user.username.lower() == 'cashier':
        role = 'cashier'

    log_activity(user, 'LOGIN', 'User', user.id, f"User '{user.username}' logged in successfully.")

    return Response({
        'token': token.key,
        'username': user.username,
        'role': role
    })