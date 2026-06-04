from django.urls import path
from .views import PaymentView, PaymentDetailView, PaymentListView

urlpatterns = [
    path("", PaymentListView.as_view(), name="payment-list"),
    path("process-payment/", PaymentView.as_view(), name="process-payment"),
    path("<uuid:payment_id>/", PaymentDetailView.as_view(), name="payment-detail"),
]