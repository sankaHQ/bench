from orders.models import Order

LEGAL_TRANSITIONS: dict[str, tuple[str, ...]] = {
    Order.Status.DRAFT: (Order.Status.SUBMITTED, Order.Status.CANCELLED),
    Order.Status.SUBMITTED: (Order.Status.APPROVED, Order.Status.CANCELLED),
    Order.Status.APPROVED: (Order.Status.SHIPPED,),
    Order.Status.SHIPPED: (),
    Order.Status.CANCELLED: (),
}
