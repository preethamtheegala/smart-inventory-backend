from django.db import models
from django.contrib.auth.models import User
from django.utils import timezone


class Supplier(models.Model):
    STATUS_CHOICES = (
        ('active', 'Active'),
        ('inactive', 'Inactive'),
    )
    name = models.CharField(max_length=200)
    company_name = models.CharField(max_length=200, blank=True)
    phone = models.CharField(max_length=50, blank=True)
    email = models.EmailField(blank=True)
    address = models.TextField(blank=True)
    tax_id = models.CharField(max_length=100, blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='active')
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.name} ({self.company_name or 'Supplier'})"


class Customer(models.Model):
    name = models.CharField(max_length=200)
    phone = models.CharField(max_length=50, blank=True)
    email = models.EmailField(blank=True)
    address = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.name


class Product(models.Model):
    name = models.CharField(max_length=200)
    category = models.CharField(max_length=100)
    price = models.DecimalField(max_digits=10, decimal_places=2) # Selling Price
    cost_price = models.DecimalField(max_digits=10, decimal_places=2, default=0.00) # Purchase/Cost Price
    quantity = models.IntegerField(default=0)
    min_stock_threshold = models.IntegerField(default=10) # Custom low-stock threshold
    sku = models.CharField(max_length=100, blank=True, null=True)
    supplier = models.ForeignKey(Supplier, on_delete=models.SET_NULL, null=True, blank=True, related_name='products')
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.name

    @property
    def is_low_stock(self):
        return self.quantity < self.min_stock_threshold

    @property
    def is_out_of_stock(self):
        return self.quantity <= 0


class ProductBatch(models.Model):
    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name='batches')
    batch_number = models.CharField(max_length=100)
    expiry_date = models.DateField(null=True, blank=True)
    quantity = models.IntegerField(default=0)
    purchase_price = models.DecimalField(max_digits=10, decimal_places=2, default=0.00)
    supplier = models.ForeignKey(Supplier, on_delete=models.SET_NULL, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.product.name} - Batch {self.batch_number} (Exp: {self.expiry_date})"

    @property
    def is_expired(self):
        if not self.expiry_date:
            return False
        return self.expiry_date < timezone.now().date()

    @property
    def is_expiring_soon(self):
        if not self.expiry_date:
            return False
        today = timezone.now().date()
        return today <= self.expiry_date <= today + timezone.timedelta(days=30)


class Purchase(models.Model):
    supplier = models.ForeignKey(Supplier, on_delete=models.CASCADE, related_name='purchases')
    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name='purchases')
    quantity = models.IntegerField()
    cost_price = models.DecimalField(max_digits=10, decimal_places=2)
    total_cost = models.DecimalField(max_digits=12, decimal_places=2)
    invoice_no = models.CharField(max_length=100, blank=True)
    notes = models.TextField(blank=True)
    batch_number = models.CharField(max_length=100, blank=True)
    expiry_date = models.DateField(null=True, blank=True)
    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True)
    purchase_date = models.DateTimeField(default=timezone.now)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"PO #{self.id} - {self.product.name} x {self.quantity}"


class Sale(models.Model):
    STATUS_CHOICES = (
        ('completed', 'Completed'),
        ('partially_returned', 'Partially Returned'),
        ('returned', 'Returned'),
    )
    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name='sales')
    customer = models.ForeignKey(Customer, on_delete=models.SET_NULL, null=True, blank=True, related_name='sales')
    quantity = models.IntegerField()
    price = models.DecimalField(max_digits=10, decimal_places=2)
    subtotal = models.DecimalField(max_digits=10, decimal_places=2, default=0.00)
    discount_percent = models.DecimalField(max_digits=5, decimal_places=2, default=0.00)
    discount_amount = models.DecimalField(max_digits=10, decimal_places=2, default=0.00)
    tax_percent = models.DecimalField(max_digits=5, decimal_places=2, default=0.00)
    tax_amount = models.DecimalField(max_digits=10, decimal_places=2, default=0.00)
    total = models.DecimalField(max_digits=10, decimal_places=2) # Grand Total
    cost_price = models.DecimalField(max_digits=10, decimal_places=2, default=0.00) # Snapshot of unit cost for COGS
    status = models.CharField(max_length=30, choices=STATUS_CHOICES, default='completed')
    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Sale #{self.id} - {self.product.name} ({self.quantity} pcs)"

    @property
    def cogs(self):
        return self.cost_price * self.quantity

    @property
    def gross_profit(self):
        return self.total - self.cogs


class SaleReturn(models.Model):
    sale = models.ForeignKey(Sale, on_delete=models.CASCADE, related_name='returns')
    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name='returns')
    quantity = models.IntegerField()
    refund_amount = models.DecimalField(max_digits=10, decimal_places=2)
    reason = models.CharField(max_length=255)
    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Return #{self.id} for Sale #{self.sale.id} ({self.quantity} pcs)"


class InventoryMovement(models.Model):
    MOVEMENT_TYPES = (
        ('PURCHASE', 'Stock-In (Purchase)'),
        ('SALE', 'Stock-Out (Sale)'),
        ('SALE_RETURN', 'Stock-In (Sale Return)'),
        ('MANUAL_ADJUSTMENT', 'Manual Adjustment'),
    )
    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name='movements')
    movement_type = models.CharField(max_length=30, choices=MOVEMENT_TYPES)
    previous_quantity = models.IntegerField()
    new_quantity = models.IntegerField()
    quantity_changed = models.IntegerField() # Positive for stock in, negative for stock out
    reason = models.CharField(max_length=255, blank=True)
    reference_id = models.CharField(max_length=100, blank=True) # e.g. "Sale #12" or "PO #4"
    user = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"[{self.movement_type}] {self.product.name}: {self.previous_quantity} -> {self.new_quantity} ({self.quantity_changed:+d})"


class ActivityLog(models.Model):
    user = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True)
    action = models.CharField(max_length=100) # CREATE, UPDATE, DELETE, ADJUST, RETURN, LOGIN, LOGOUT
    entity = models.CharField(max_length=100) # Product, Sale, Purchase, Supplier, Customer, etc.
    entity_id = models.CharField(max_length=100, blank=True)
    description = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"[{self.action}] {self.entity} #{self.entity_id} by {self.user}"


class Notification(models.Model):
    NOTIFICATION_TYPES = (
        ('low_stock', 'Low Stock Alert'),
        ('out_of_stock', 'Out of Stock Alert'),
        ('expiry', 'Expiry Warning'),
        ('sale', 'Sales Alert'),
        ('adjustment', 'Stock Adjustment'),
        ('system', 'System Notification'),
    )
    user = models.ForeignKey(User, on_delete=models.CASCADE, null=True, blank=True)
    title = models.CharField(max_length=200)
    message = models.TextField()
    notification_type = models.CharField(max_length=30, choices=NOTIFICATION_TYPES, default='system')
    is_read = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"[{self.notification_type}] {self.title}"