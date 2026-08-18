from decimal import Decimal
from rest_framework import serializers
from .models import (
    Supplier, Customer, Product, ProductBatch, Purchase,
    Sale, SaleReturn, InventoryMovement, ActivityLog, Notification
)



class SupplierSerializer(serializers.ModelSerializer):
    total_purchases = serializers.SerializerMethodField()
    total_spend = serializers.SerializerMethodField()
    products_count = serializers.SerializerMethodField()

    class Meta:
        model = Supplier
        fields = '__all__'

    def get_total_purchases(self, obj):
        return obj.purchases.count()

    def get_total_spend(self, obj):
        return sum(p.total_cost for p in obj.purchases.all())

    def get_products_count(self, obj):
        return obj.products.count()


class CustomerSerializer(serializers.ModelSerializer):
    total_orders = serializers.SerializerMethodField()
    total_spent = serializers.SerializerMethodField()

    class Meta:
        model = Customer
        fields = '__all__'

    def get_total_orders(self, obj):
        return obj.sales.count()

    def get_total_spent(self, obj):
        return sum(s.total for s in obj.sales.all())


class ProductBatchSerializer(serializers.ModelSerializer):
    product_name = serializers.CharField(source='product.name', read_only=True)
    supplier_name = serializers.CharField(source='supplier.name', read_only=True)
    is_expired = serializers.ReadOnlyField()
    is_expiring_soon = serializers.ReadOnlyField()

    class Meta:
        model = ProductBatch
        fields = '__all__'


class ProductSerializer(serializers.ModelSerializer):
    supplier_name = serializers.CharField(source='supplier.name', read_only=True)
    is_low_stock = serializers.ReadOnlyField()
    is_out_of_stock = serializers.ReadOnlyField()
    batches = ProductBatchSerializer(many=True, read_only=True)

    class Meta:
        model = Product
        fields = '__all__'

    def validate_price(self, value):
        if value < 0:
            raise serializers.ValidationError("Selling price cannot be negative.")
        return value

    def validate_cost_price(self, value):
        if value < 0:
            raise serializers.ValidationError("Cost price cannot be negative.")
        return value

    def validate_quantity(self, value):
        if value < 0:
            raise serializers.ValidationError("Quantity cannot be negative.")
        return value

    def validate_min_stock_threshold(self, value):
        if value < 0:
            raise serializers.ValidationError("Threshold cannot be negative.")
        return value


class PurchaseSerializer(serializers.ModelSerializer):
    product_name = serializers.CharField(source='product.name', read_only=True)
    supplier_name = serializers.CharField(source='supplier.name', read_only=True)
    created_by_username = serializers.CharField(source='created_by.username', read_only=True)

    class Meta:
        model = Purchase
        fields = '__all__'
        read_only_fields = ('total_cost', 'created_by')

    def validate(self, attrs):
        quantity = attrs.get('quantity')
        cost_price = attrs.get('cost_price')

        if quantity is not None and quantity <= 0:
            raise serializers.ValidationError({"quantity": "Purchase quantity must be greater than zero."})

        if cost_price is not None and cost_price < 0:
            raise serializers.ValidationError({"cost_price": "Cost price cannot be negative."})

        if quantity is not None and cost_price is not None:
            attrs['total_cost'] = quantity * cost_price

        return attrs


class SaleReturnSerializer(serializers.ModelSerializer):
    product_name = serializers.CharField(source='product.name', read_only=True)
    created_by_username = serializers.CharField(source='created_by.username', read_only=True)

    class Meta:
        model = SaleReturn
        fields = '__all__'
        read_only_fields = ('refund_amount', 'created_by')

    def validate(self, attrs):
        quantity = attrs.get('quantity')
        sale = attrs.get('sale')
        product = attrs.get('product') or (sale.product if sale else None)

        if not product and sale:
            attrs['product'] = sale.product

        if quantity is not None and quantity <= 0:
            raise serializers.ValidationError({"quantity": "Return quantity must be at least 1."})

        if sale and quantity is not None:
            # Check previously returned quantity for this sale
            already_returned = sum(r.quantity for r in sale.returns.all())
            max_returnable = sale.quantity - already_returned
            if quantity > max_returnable:
                raise serializers.ValidationError({
                    "quantity": f"Cannot return {quantity} units. Only {max_returnable} unit(s) eligible for return from Sale #{sale.id}."
                })

            # Calculate proportional refund amount based on sale price/discount
            unit_effective_price = Decimal(str(sale.total)) / Decimal(str(sale.quantity)) if sale.quantity > 0 else Decimal(str(sale.price))
            attrs['refund_amount'] = (unit_effective_price * Decimal(str(quantity))).quantize(Decimal('0.01'))

        return attrs


class SaleSerializer(serializers.ModelSerializer):
    product_name = serializers.CharField(source='product.name', read_only=True)
    product_category = serializers.CharField(source='product.category', read_only=True)
    customer_name = serializers.CharField(source='customer.name', read_only=True)
    created_by_username = serializers.CharField(source='created_by.username', read_only=True)
    returns = SaleReturnSerializer(many=True, read_only=True)
    returned_quantity = serializers.SerializerMethodField()

    class Meta:
        model = Sale
        fields = '__all__'
        read_only_fields = ('subtotal', 'discount_amount', 'tax_amount', 'total', 'cost_price', 'created_by', 'status')

    def get_returned_quantity(self, obj):
        return sum(r.quantity for r in obj.returns.all())

    def validate(self, attrs):
        quantity = attrs.get('quantity')
        product = attrs.get('product')
        price = attrs.get('price')
        discount_percent = attrs.get('discount_percent', Decimal('0.00'))
        tax_percent = attrs.get('tax_percent', Decimal('0.00'))

        if quantity is not None and quantity <= 0:
            raise serializers.ValidationError({"quantity": "Quantity must be greater than zero."})

        if price is None and product:
            price = product.price
            attrs['price'] = price

        if price is not None and price < 0:
            raise serializers.ValidationError({"price": "Price cannot be negative."})

        d_pct = Decimal(str(discount_percent)) if discount_percent is not None else Decimal('0.00')
        t_pct = Decimal(str(tax_percent)) if tax_percent is not None else Decimal('0.00')

        if d_pct < 0 or d_pct > 100:
            raise serializers.ValidationError({"discount_percent": "Discount percentage must be between 0 and 100."})

        if t_pct < 0 or t_pct > 100:
            raise serializers.ValidationError({"tax_percent": "Tax percentage cannot be negative."})

        # Calculate subtotal, discount, tax, total with Decimal arithmetic
        if price is not None and quantity is not None:
            dec_price = Decimal(str(price))
            dec_qty = Decimal(str(quantity))

            subtotal = dec_price * dec_qty
            discount_amount = (subtotal * (d_pct / Decimal('100.0'))).quantize(Decimal('0.01'))
            after_discount = subtotal - discount_amount
            tax_amount = (after_discount * (t_pct / Decimal('100.0'))).quantize(Decimal('0.01'))
            grand_total = after_discount + tax_amount

            attrs['subtotal'] = subtotal
            attrs['discount_percent'] = d_pct
            attrs['discount_amount'] = discount_amount
            attrs['tax_percent'] = t_pct
            attrs['tax_amount'] = tax_amount
            attrs['total'] = grand_total

            # Snapshot product cost price
            if product:
                attrs['cost_price'] = product.cost_price

        # Check available stock
        if not self.instance and product and quantity is not None:
            if product.quantity < quantity:
                raise serializers.ValidationError({
                    "quantity": f"Insufficient stock. Only {product.quantity} unit(s) available for '{product.name}'."
                })

        return attrs



class InventoryMovementSerializer(serializers.ModelSerializer):
    product_name = serializers.CharField(source='product.name', read_only=True)
    user_username = serializers.CharField(source='user.username', read_only=True)

    class Meta:
        model = InventoryMovement
        fields = '__all__'


class ActivityLogSerializer(serializers.ModelSerializer):
    user_username = serializers.CharField(source='user.username', read_only=True)

    class Meta:
        model = ActivityLog
        fields = '__all__'


class NotificationSerializer(serializers.ModelSerializer):
    class Meta:
        model = Notification
        fields = '__all__'


class StockAdjustmentSerializer(serializers.Serializer):
    product_id = serializers.IntegerField()
    adjustment_type = serializers.ChoiceField(choices=['INCREASE', 'DECREASE', 'SET'])
    quantity = serializers.IntegerField(min_value=0)
    reason = serializers.CharField(max_length=255)