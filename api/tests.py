from django.test import TestCase
from django.contrib.auth.models import User
from django.utils import timezone
from rest_framework.test import APIClient
from rest_framework import status
from datetime import timedelta
from .models import (
    Supplier, Customer, Product, ProductBatch, Purchase,
    Sale, SaleReturn, InventoryMovement, ActivityLog
)


class ComprehensiveInventoryVerificationTests(TestCase):
    def setUp(self):
        self.client = APIClient()

        # Users
        self.owner = User.objects.create_user(username='owner', password='ownerpassword123')
        self.cashier = User.objects.create_user(username='cashier', password='cashierpassword123')

        # Supplier & Customer
        self.supplier = Supplier.objects.create(
            name='TechDistro Ltd',
            company_name='Tech Distributors Global',
            phone='+91 9876543210',
            email='sales@techdistro.com',
            tax_id='GSTIN1234567'
        )
        self.customer = Customer.objects.create(
            name='John Doe Enterprises',
            phone='+91 9123456780',
            email='john@example.com'
        )

        # Product
        self.product = Product.objects.create(
            name='Dell UltraSharp 27 Monitor',
            category='Electronics',
            price=450.00,
            cost_price=300.00,
            quantity=10,
            min_stock_threshold=5,
            supplier=self.supplier
        )

    # 1. Supplier Creation
    def test_supplier_creation(self):
        self.client.force_authenticate(user=self.owner)
        res = self.client.post('/api/suppliers/', {
            'name': 'Apex Components Ltd',
            'company_name': 'Apex Global',
            'phone': '+91 9888877777',
            'email': 'sales@apex.com',
            'tax_id': 'GSTIN78910',
            'status': 'active'
        })
        self.assertEqual(res.status_code, status.HTTP_201_CREATED)
        self.assertEqual(res.data['name'], 'Apex Components Ltd')
        self.assertTrue(Supplier.objects.filter(name='Apex Components Ltd').exists())

    # 2. Purchase Creation & Stock Increase
    def test_purchase_creation_and_stock_increase(self):
        self.assertEqual(self.product.quantity, 10)
        self.client.force_authenticate(user=self.owner)
        res = self.client.post('/api/purchases/', {
            'supplier': self.supplier.id,
            'product': self.product.id,
            'quantity': 20,
            'cost_price': 280.00,
            'invoice_no': 'INV-2026-PO-01',
            'batch_number': 'BATCH-MON-01',
            'expiry_date': (timezone.now().date() + timedelta(days=180)).strftime('%Y-%m-%d')
        })
        self.assertEqual(res.status_code, status.HTTP_201_CREATED)
        self.assertEqual(float(res.data['total_cost']), 20 * 280.00)

        self.product.refresh_from_db()
        self.assertEqual(self.product.quantity, 30) # 10 + 20
        self.assertEqual(float(self.product.cost_price), 280.00)

    # 3. Sale Stock Reduction
    def test_sale_stock_reduction(self):
        self.assertEqual(self.product.quantity, 10)
        self.client.force_authenticate(user=self.cashier)
        res = self.client.post('/api/sales/', {
            'product': self.product.id,
            'quantity': 4,
            'price': 450.00
        })
        self.assertEqual(res.status_code, status.HTTP_201_CREATED)

        self.product.refresh_from_db()
        self.assertEqual(self.product.quantity, 6) # 10 - 4

    # 4. Sale Return Stock Restoration
    def test_sale_return_stock_restoration(self):
        self.client.force_authenticate(user=self.cashier)
        sale_res = self.client.post('/api/sales/', {
            'product': self.product.id,
            'quantity': 6,
            'price': 450.00
        })
        sale_id = sale_res.data['id']
        self.product.refresh_from_db()
        self.assertEqual(self.product.quantity, 4)

        ret_res = self.client.post('/api/returns/', {
            'sale': sale_id,
            'product': self.product.id,
            'quantity': 2,
            'reason': 'Damaged packaging'
        })
        self.assertEqual(ret_res.status_code, status.HTTP_201_CREATED)
        self.assertEqual(float(ret_res.data['refund_amount']), 2 * 450.00)

        self.product.refresh_from_db()
        self.assertEqual(self.product.quantity, 6) # 4 + 2

    # 5. Manual Stock Adjustment
    def test_manual_stock_adjustment(self):
        self.client.force_authenticate(user=self.owner)
        res = self.client.post('/api/inventory/adjust/', {
            'product_id': self.product.id,
            'adjustment_type': 'DECREASE',
            'quantity': 3,
            'reason': 'Stock audit correction'
        })
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.product.refresh_from_db()
        self.assertEqual(self.product.quantity, 7)

        # Test Increase
        res_inc = self.client.post('/api/inventory/adjust/', {
            'product_id': self.product.id,
            'adjustment_type': 'INCREASE',
            'quantity': 5,
            'reason': 'Found misplaced stock'
        })
        self.assertEqual(res_inc.status_code, status.HTTP_200_OK)
        self.product.refresh_from_db()
        self.assertEqual(self.product.quantity, 12)

    # 6. Insufficient Stock Prevention
    def test_insufficient_stock_prevention(self):
        self.client.force_authenticate(user=self.cashier)
        # Attempt to sell 15 units when only 10 available
        res = self.client.post('/api/sales/', {
            'product': self.product.id,
            'quantity': 15,
            'price': 450.00
        })
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('quantity', res.data)
        # Verify stock remained untouched
        self.product.refresh_from_db()
        self.assertEqual(self.product.quantity, 10)

    # 7. Discount Calculation
    def test_discount_calculation(self):
        self.client.force_authenticate(user=self.cashier)
        # Sell 5 units @ 400 with 15% discount
        # Subtotal: 2000, Discount: 300, Total: 1700
        res = self.client.post('/api/sales/', {
            'product': self.product.id,
            'quantity': 5,
            'price': 400.00,
            'discount_percent': 15.0,
            'tax_percent': 0.0
        })
        self.assertEqual(res.status_code, status.HTTP_201_CREATED)
        self.assertEqual(float(res.data['subtotal']), 2000.00)
        self.assertEqual(float(res.data['discount_amount']), 300.00)
        self.assertEqual(float(res.data['total']), 1700.00)

    # 8. GST/Tax Calculation
    def test_tax_calculation(self):
        self.client.force_authenticate(user=self.cashier)
        # Sell 2 units @ 500 with 10% discount and 18% GST
        # Subtotal: 1000
        # Discount: 100 -> 900
        # GST (18% of 900): 162.00
        # Grand Total: 1062.00
        res = self.client.post('/api/sales/', {
            'product': self.product.id,
            'quantity': 2,
            'price': 500.00,
            'discount_percent': 10.0,
            'tax_percent': 18.0
        })
        self.assertEqual(res.status_code, status.HTTP_201_CREATED)
        self.assertEqual(float(res.data['subtotal']), 1000.00)
        self.assertEqual(float(res.data['discount_amount']), 100.00)
        self.assertEqual(float(res.data['tax_amount']), 162.00)
        self.assertEqual(float(res.data['total']), 1062.00)

    # 9. Profit & COGS Calculation
    def test_profit_and_cogs_calculation(self):
        # Product: price 450, cost_price 300. Sell 3 units.
        # Revenue: 1350, COGS: 900, Gross Profit: 450, Margin: (450/1350)*100 = 33.33%
        self.client.force_authenticate(user=self.owner)
        self.client.post('/api/sales/', {
            'product': self.product.id,
            'quantity': 3,
            'price': 450.00
        })

        analytics_res = self.client.get('/api/analytics/?range=today')
        self.assertEqual(analytics_res.status_code, status.HTTP_200_OK)
        data = analytics_res.data

        self.assertEqual(data['total_revenue'], 1350.00)
        self.assertEqual(data['total_cogs'], 900.00)
        self.assertEqual(data['gross_profit'], 450.00)
        self.assertEqual(data['gross_margin_percent'], 33.33)

    # 10. Owner Authorization
    def test_owner_authorization(self):
        self.client.force_authenticate(user=self.owner)
        # Owner can create products, adjust stock, create purchases, view logs
        prod_res = self.client.post('/api/products/', {
            'name': 'Owner Added Laptop',
            'category': 'Electronics',
            'price': 1200.00,
            'cost_price': 900.00,
            'quantity': 5,
            'min_stock_threshold': 2
        })
        self.assertEqual(prod_res.status_code, status.HTTP_201_CREATED)

        logs_res = self.client.get('/api/logs/')
        self.assertEqual(logs_res.status_code, status.HTTP_200_OK)

    # 11. Cashier Authorization & Restrictions
    def test_cashier_authorization(self):
        self.client.force_authenticate(user=self.cashier)

        # Cashier CAN create sales
        sale_res = self.client.post('/api/sales/', {
            'product': self.product.id,
            'quantity': 1,
            'price': 450.00
        })
        self.assertEqual(sale_res.status_code, status.HTTP_201_CREATED)

        # Cashier is BLOCKED (403) from creating products
        prod_block = self.client.post('/api/products/', {
            'name': 'Unauthorized Product',
            'price': 100.00,
            'quantity': 5
        })
        self.assertEqual(prod_block.status_code, status.HTTP_403_FORBIDDEN)

        # Cashier is BLOCKED (403) from creating suppliers
        sup_block = self.client.post('/api/suppliers/', {'name': 'Unauthorized Supplier'})
        self.assertEqual(sup_block.status_code, status.HTTP_403_FORBIDDEN)

        # Cashier is BLOCKED (403) from creating purchases
        po_block = self.client.post('/api/purchases/', {
            'supplier': self.supplier.id,
            'product': self.product.id,
            'quantity': 5,
            'cost_price': 100.00
        })
        self.assertEqual(po_block.status_code, status.HTTP_403_FORBIDDEN)

        # Cashier is BLOCKED (403) from manual stock adjustments
        adj_block = self.client.post('/api/inventory/adjust/', {
            'product_id': self.product.id,
            'adjustment_type': 'INCREASE',
            'quantity': 5,
            'reason': 'Unauthorized'
        })
        self.assertEqual(adj_block.status_code, status.HTTP_403_FORBIDDEN)

        # Cashier is BLOCKED (403) from deleting sales
        sale_del_block = self.client.delete(f'/api/sales/{sale_res.data["id"]}/')
        self.assertEqual(sale_del_block.status_code, status.HTTP_403_FORBIDDEN)

        # Cashier is BLOCKED (403) from viewing system activity logs
        logs_block = self.client.get('/api/logs/')
        self.assertEqual(logs_block.status_code, status.HTTP_403_FORBIDDEN)

    # 12. Inventory Movement Creation
    def test_inventory_movement_creation(self):
        self.client.force_authenticate(user=self.owner)

        # 1. Purchase movement
        self.client.post('/api/purchases/', {
            'supplier': self.supplier.id,
            'product': self.product.id,
            'quantity': 5,
            'cost_price': 300.00
        })
        mov_purchase = InventoryMovement.objects.filter(product=self.product, movement_type='PURCHASE').latest('id')
        self.assertEqual(mov_purchase.previous_quantity, 10)
        self.assertEqual(mov_purchase.new_quantity, 15)
        self.assertEqual(mov_purchase.quantity_changed, 5)

        # 2. Sale movement
        sale_res = self.client.post('/api/sales/', {
            'product': self.product.id,
            'quantity': 3,
            'price': 450.00
        })
        mov_sale = InventoryMovement.objects.filter(product=self.product, movement_type='SALE').latest('id')
        self.assertEqual(mov_sale.previous_quantity, 15)
        self.assertEqual(mov_sale.new_quantity, 12)
        self.assertEqual(mov_sale.quantity_changed, -3)

        # 3. Return movement
        self.client.post('/api/returns/', {
            'sale': sale_res.data['id'],
            'product': self.product.id,
            'quantity': 1,
            'reason': 'Returned item'
        })
        mov_ret = InventoryMovement.objects.filter(product=self.product, movement_type='SALE_RETURN').latest('id')
        self.assertEqual(mov_ret.previous_quantity, 12)
        self.assertEqual(mov_ret.new_quantity, 13)
        self.assertEqual(mov_ret.quantity_changed, 1)

        # 4. Adjustment movement
        self.client.post('/api/inventory/adjust/', {
            'product_id': self.product.id,
            'adjustment_type': 'DECREASE',
            'quantity': 2,
            'reason': 'Physical count difference'
        })
        mov_adj = InventoryMovement.objects.filter(product=self.product, movement_type='MANUAL_ADJUSTMENT').latest('id')
        self.assertEqual(mov_adj.previous_quantity, 13)
        self.assertEqual(mov_adj.new_quantity, 11)
        self.assertEqual(mov_adj.quantity_changed, -2)

    # 13. Activity Log Creation
    def test_activity_log_creation(self):
        self.client.force_authenticate(user=self.owner)
        initial_logs_count = ActivityLog.objects.count()

        # Perform action
        res = self.client.post('/api/products/', {
            'name': 'Monitored Product',
            'category': 'Electronics',
            'price': 50.00,
            'cost_price': 30.00,
            'quantity': 10
        })
        self.assertEqual(res.status_code, status.HTTP_201_CREATED)

        new_logs_count = ActivityLog.objects.count()
        self.assertGreater(new_logs_count, initial_logs_count)
        latest_log = ActivityLog.objects.latest('id')
        self.assertEqual(latest_log.entity, 'Product')
        self.assertEqual(latest_log.action, 'CREATE')
        self.assertEqual(latest_log.user, self.owner)

