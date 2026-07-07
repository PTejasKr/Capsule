# Business Requirement Document: E-Commerce System

## 1. Overview
This document describes the business processes and requirements for the Core E-Commerce Ordering and User management systems.

## 2. User Registration & Onboarding Workflow
All users must register and complete email verification before they can place orders.

### 2.1 Process Sequence
1. **Submit Registration Form**: User enters email, password, and name.
2. **State: Pending Verification**: User account is created in `PENDING` state. An email verification token is emailed.
3. **Verify Email**: User clicks verification link in email.
4. **State: Active**: User account state transitions to `ACTIVE`. The user is redirected to the store dashboard.

```
[Idle] ➔ Submit Form ➔ [Pending Verification] ➔ Verify Link ➔ [Active]
```

### 2.2 Business Rules
- Registration must fail if the email domain is on our blocked domains list.
- Verification links expire after 24 hours.

---

## 3. Order Processing Workflow
This defines the lifecycle of an order from creation to delivery.

### 3.1 Order State Transitions
An order must follow these strict state transitions:

1. **Created**: Order initialized by user. (State: `CREATED`)
2. **Payment Processing**: User submits payment details. (State: `PAYMENT_PENDING`)
3. **Paid / Approved**: Payment provider confirms charge. (State: `PAID`)
4. **Fulfillment**: Warehouse processes item shipping. (State: `FULFILLING`)
5. **Shipped**: Carrier accepts parcel and generates tracking ID. (State: `SHIPPED`)
6. **Completed**: Customer receives delivery. (State: `COMPLETED`)

### 3.2 State Diagram Transitions
```
[CREATED] ➔ [PAYMENT_PENDING] ➔ [PAID] ➔ [FULFILLING] ➔ [SHIPPED] ➔ [COMPLETED]
```

### 3.3 Business Rules for Transitions
- **Payment Failure**: If payment fails during `PAYMENT_PENDING`, the state reverts to `CREATED`.
- **Cancellation**: An order can only be cancelled by the user if it is in `CREATED` or `PAYMENT_PENDING` states. Once it transitions to `PAID`, cancellation is blocked, and refund procedures must be initiated instead.
- **Refund State**: If an order in `PAID` or `FULFILLING` state is cancelled by an administrator, the state transitions to `REFUNDED`.

---

## 4. Security & Compliance
- Customer passwords must be hashed using bcrypt.
- Payment details must never be stored on our local database. We must use tokenized transactions via Stripe.
