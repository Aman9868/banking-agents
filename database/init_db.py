"""Database initialization and mock seed data script."""

import asyncio
from datetime import datetime, timezone
from sqlalchemy import select
from database.connection import engine, Base, AsyncSessionLocal
from database.models.banking import (
    Customer,
    Account,
    Beneficiary,
    Transaction,
    Card,
    Biller,
    KnowledgeDoc
)


async def init_database():
    """Create all tables in the configured database."""
    from sqlalchemy import text
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await conn.execute(text("ALTER TABLE chat_messages ADD COLUMN IF NOT EXISTS widget_type VARCHAR(64);"))
        await conn.execute(text("ALTER TABLE chat_messages ADD COLUMN IF NOT EXISTS widget_data JSON;"))


async def seed_mock_data():
    """Seed sample customer, account, cards, billers, and knowledge base docs."""
    async with AsyncSessionLocal() as session:
        # Check customer
        res = await session.execute(select(Customer).where(Customer.external_id == "CUST-1001"))
        customer = res.scalar_one_or_none()
        if customer:
            # Ensure primary account balance is replenished to ₹100,000 for test reproducibility
            acc_res = await session.execute(select(Account).where(Account.customer_id == customer.id, Account.account_number == "SB10001234"))
            primary_acc = acc_res.scalar_one_or_none()
            if primary_acc:
                primary_acc.balance = 100000.0
            # Ensure declined transaction timestamp is refreshed for test reproducibility
            tx_res = await session.execute(select(Transaction).where(Transaction.transaction_ref == "TXN-10091"))
            dec_tx = tx_res.scalar_one_or_none()
            if dec_tx:
                dec_tx.created_at = datetime.now(timezone.utc).replace(tzinfo=None)
            await session.commit()
            return

        if not customer:
            # 1. Create primary sample customer: Amanpreet Singh
            customer = Customer(
                external_id="CUST-1001",
                full_name="Amanpreet Singh",
                email="amanpreet.singh@example.com",
                phone="+919876543210",
                date_of_birth="1997-03-12",
                kyc_status="VERIFIED",
                risk_tier="LOW"
            )
            session.add(customer)
            await session.flush()

            # 2. Add savings account with ₹100,000 balance
            account = Account(
                customer_id=customer.id,
                account_number="SB10001234",
                account_type="SAVINGS",
                balance=100000.0,
                currency="INR",
                status="ACTIVE"
            )
            session.add(account)
            await session.flush()

            # 3. Add Rahul as beneficiary
            beneficiary = Beneficiary(
                customer_id=customer.id,
                name="Rahul Sharma",
                account_number="SB90007788",
                ifsc_code="HDFC0001234",
                status="ACTIVE"
            )
            session.add(beneficiary)
            await session.flush()

            # 4. Add past declined transaction for support demonstration
            declined_tx = Transaction(
                transaction_ref="TXN-10091",
                customer_id=customer.id,
                source_account_id=account.id,
                beneficiary_id=beneficiary.id,
                amount=25000.0,
                currency="INR",
                status="DECLINED",
                failure_reason="BENEFICIARY_SECURITY_VERIFICATION_INCOMPLETE",
                fraud_score=0.45,
                idempotency_key="SEED-DECLINED-10091"
            )
            session.add(declined_tx)

        # 5. Seed Cards if not present
        card_res = await session.execute(select(Card).where(Card.customer_id == customer.id))
        if not card_res.scalars().first():
            debit_card = Card(
                customer_id=customer.id,
                card_number="4532891234567788",
                card_type="DEBIT",
                network="VISA",
                expiry_date="08/29",
                status="ACTIVE",
                daily_atm_limit=50000.0,
                daily_online_limit=75000.0,
                is_international_enabled=True
            )
            credit_card = Card(
                customer_id=customer.id,
                card_number="5105105105101234",
                card_type="CREDIT",
                network="MASTERCARD",
                expiry_date="11/27",
                status="ACTIVE",
                daily_atm_limit=25000.0,
                daily_online_limit=150000.0,
                is_international_enabled=False
            )
            session.add_all([debit_card, credit_card])

        # 6. Seed Billers if not present
        biller_res = await session.execute(select(Biller))
        if not biller_res.scalars().first():
            billers = [
                Biller(biller_code="BIL-ELEC-01", name="Tata Power", category="ELECTRICITY", min_amount=100.0),
                Biller(biller_code="BIL-BB-01", name="Airtel Broadband", category="BROADBAND", min_amount=500.0),
                Biller(biller_code="BIL-CC-01", name="HDFC Credit Card Bill", category="CREDIT_CARD", min_amount=500.0)
            ]
            session.add_all(billers)

        # 7. Seed Knowledge Base Documents if not present
        doc_res = await session.execute(select(KnowledgeDoc))
        if not doc_res.scalars().first():
            docs = [
                KnowledgeDoc(
                    doc_id="DOC-SAVINGS-RATE",
                    title="Savings Account Interest Rates",
                    category="ACCOUNTS",
                    content="Our standard savings account offers an annual interest rate of 3.50% compounded quarterly. Senior citizens enjoy an additional 0.50% rate.",
                    keywords="savings interest rate rate-of-interest percentage"
                ),
                KnowledgeDoc(
                    doc_id="DOC-CARD-FREEZE",
                    title="Card Security & Freeze Policy",
                    category="CARDS",
                    content="If your debit or credit card is lost, stolen, or misplaced, you can instantly freeze it in the banking chat. Freezing prevents all POS, online, and ATM transactions immediately. You can unfreeze it anytime if found, or request a free replacement card.",
                    keywords="freeze card lost stolen replacement block"
                ),
                KnowledgeDoc(
                    doc_id="DOC-PERSONAL-LOAN",
                    title="Personal Loan Guidelines and Eligibility",
                    category="LOANS",
                    content="Personal loans range from ₹50,000 to ₹15,00,000 with flexible tenures from 12 to 60 months. Interest rates start from 10.50% p.a. Applicants must have a minimum monthly net salary of ₹25,000.",
                    keywords="personal loan interest emi tenure eligibility documents"
                ),
                KnowledgeDoc(
                    doc_id="DOC-TRANSFER-LIMITS",
                    title="Fund Transfer Limits and Charges",
                    category="TRANSFERS",
                    content="IMPS and UPI transfers are free with a standard daily limit of ₹1,00,000. NEFT and RTGS transfers have no maximum limit and zero transaction fees during regular banking hours.",
                    keywords="transfer limits charges fees imps upi neft rtgs"
                )
            ]
            session.add_all(docs)

        await session.commit()
        print("Database initialized and seeded with Customer, Account, Beneficiary, Cards, Billers, and Knowledge Docs.")


async def main():
    await init_database()
    await seed_mock_data()
    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
