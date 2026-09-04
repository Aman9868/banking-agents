"""Repository for secure, parameterized data access on Customers, Accounts, and Transactions."""

from typing import List, Optional, Any
from datetime import datetime, timezone
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
from database.models.banking import (
    Customer,
    Account,
    Beneficiary,
    Transaction,
    HumanReviewTask,
    AuditLog,
    Card,
    LoanApplication,
    Biller,
    BillPayment,
    SupportTicket,
    KnowledgeDoc,
    ChatSession,
    ChatMessage
)


class BankingRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def get_customer_by_external_id(self, external_id: str) -> Optional[Customer]:
        query = select(Customer).where(Customer.external_id == external_id)
        result = await self.session.execute(query)
        return result.scalar_one_or_none()

    async def get_customer_by_id(self, customer_id: int) -> Optional[Customer]:
        return await self.session.get(Customer, customer_id)


    async def get_accounts_by_customer_id(self, customer_id: int) -> List[Account]:
        query = select(Account).where(Account.customer_id == customer_id)
        result = await self.session.execute(query)
        return list(result.scalars().all())

    async def get_account_by_number(self, account_number: str) -> Optional[Account]:
        query = select(Account).where(Account.account_number == account_number)
        result = await self.session.execute(query)
        return result.scalar_one_or_none()

    async def get_beneficiaries(self, customer_id: int) -> List[Beneficiary]:
        query = select(Beneficiary).where(Beneficiary.customer_id == customer_id)
        result = await self.session.execute(query)
        return list(result.scalars().all())

    async def find_beneficiary_by_name(self, customer_id: int, name: str) -> Optional[Beneficiary]:
        query = select(Beneficiary).where(
            Beneficiary.customer_id == customer_id,
            Beneficiary.name.ilike(f"%{name}%")
        )
        result = await self.session.execute(query)
        return result.scalars().first()

    async def create_beneficiary(
        self,
        customer_id: int,
        name: str,
        account_number: str,
        ifsc_code: str = "NOVA0001001",
        status: str = "ACTIVE"
    ) -> Beneficiary:
        clean_name = " ".join(w.capitalize() for w in name.strip().split())
        existing = await self.find_beneficiary_by_name(customer_id, clean_name)
        if existing:
            existing.account_number = account_number.strip()
            existing.ifsc_code = ifsc_code.strip().upper()
            existing.status = status
            await self.session.commit()
            return existing

        bene = Beneficiary(
            customer_id=customer_id,
            name=clean_name,
            account_number=account_number.strip(),
            ifsc_code=ifsc_code.strip().upper(),
            status=status
        )
        self.session.add(bene)
        await self.session.commit()
        return bene

    async def get_transaction_by_ref(self, transaction_ref: str) -> Optional[Transaction]:
        from sqlalchemy.orm import selectinload
        query = (
            select(Transaction)
            .options(selectinload(Transaction.beneficiary), selectinload(Transaction.source_account))
            .where(Transaction.transaction_ref == transaction_ref)
        )
        result = await self.session.execute(query)
        return result.scalar_one_or_none()

    async def get_recent_transactions(self, customer_id: int, limit: int = 5) -> List[Transaction]:
        from sqlalchemy.orm import selectinload
        query = (
            select(Transaction)
            .options(selectinload(Transaction.beneficiary), selectinload(Transaction.source_account))
            .where(Transaction.customer_id == customer_id)
            .order_by(Transaction.created_at.desc())
            .limit(limit)
        )
        result = await self.session.execute(query)
        return list(result.scalars().all())

    async def get_transactions_in_range(
        self,
        customer_id: int,
        start_date: Any,
        end_date: Any,
        account_id: Optional[int] = None
    ) -> List[Transaction]:
        """Fetch transactions within a date range ordered chronologically."""
        from sqlalchemy.orm import selectinload
        if hasattr(start_date, "tzinfo") and start_date.tzinfo:
            start_date = start_date.replace(tzinfo=None)
        if hasattr(end_date, "tzinfo") and end_date.tzinfo:
            end_date = end_date.replace(tzinfo=None)

        conditions = [
            Transaction.customer_id == customer_id,
            Transaction.created_at >= start_date,
            Transaction.created_at <= end_date
        ]
        if account_id is not None:
            conditions.append(Transaction.source_account_id == account_id)

        query = (
            select(Transaction)
            .options(selectinload(Transaction.beneficiary), selectinload(Transaction.source_account))
            .where(*conditions)
            .order_by(Transaction.created_at.asc())
        )
        result = await self.session.execute(query)
        return list(result.scalars().all())


    async def create_transaction(
        self,
        transaction_ref: str,
        customer_id: int,
        source_account_id: int,
        beneficiary_id: Optional[int],
        amount: float,
        status: str,
        fraud_score: float,
        idempotency_key: str,
        failure_reason: Optional[str] = None
    ) -> Transaction:
        tx = Transaction(
            transaction_ref=transaction_ref,
            customer_id=customer_id,
            source_account_id=source_account_id,
            beneficiary_id=beneficiary_id,
            amount=amount,
            status=status,
            fraud_score=fraud_score,
            idempotency_key=idempotency_key,
            failure_reason=failure_reason
        )
        self.session.add(tx)
        await self.session.flush()
        return tx

    async def update_account_balance(self, account_id: int, delta: float) -> bool:
        account = await self.session.get(Account, account_id)
        if not account or account.balance + delta < 0:
            return False
        account.balance += delta
        await self.session.flush()
        return True

    async def create_review_task(
        self,
        task_ref: str,
        thread_id: str,
        customer_id: int,
        workflow_type: str,
        risk_score: float,
        reason: str,
        payload: dict
    ) -> HumanReviewTask:
        task = HumanReviewTask(
            task_ref=task_ref,
            thread_id=thread_id,
            customer_id=customer_id,
            workflow_type=workflow_type,
            risk_score=risk_score,
            reason=reason,
            payload=payload,
            status="PENDING"
        )
        self.session.add(task)
        await self.session.flush()
        return task

    async def log_audit(
        self,
        event_type: str,
        agent_id: str,
        customer_id: Optional[int],
        thread_id: Optional[str],
        payload: dict
    ):
        audit = AuditLog(
            event_type=event_type,
            agent_id=agent_id,
            customer_id=customer_id,
            thread_id=thread_id,
            payload=payload,
            timestamp=datetime.now(timezone.utc).replace(tzinfo=None)
        )
        self.session.add(audit)
        await self.session.flush()

    # --- Phase 5: Cards Repository Methods ---
    async def get_cards_by_customer_id(self, customer_id: int) -> List[Card]:
        query = select(Card).where(Card.customer_id == customer_id)
        result = await self.session.execute(query)
        return list(result.scalars().all())

    async def get_card_by_id(self, card_id: int) -> Optional[Card]:
        return await self.session.get(Card, card_id)

    async def find_card_by_type(self, customer_id: int, card_type: str = "DEBIT") -> Optional[Card]:
        query = select(Card).where(Card.customer_id == customer_id, Card.card_type.ilike(card_type))
        result = await self.session.execute(query)
        return result.scalars().first()

    async def update_card_status(self, card_id: int, new_status: str) -> bool:
        card = await self.session.get(Card, card_id)
        if not card:
            return False
        card.status = new_status
        await self.session.flush()
        return True

    async def update_card_limits(self, card_id: int, atm_limit: Optional[float] = None, online_limit: Optional[float] = None) -> bool:
        card = await self.session.get(Card, card_id)
        if not card:
            return False
        if atm_limit is not None:
            card.daily_atm_limit = atm_limit
        if online_limit is not None:
            card.daily_online_limit = online_limit
        await self.session.flush()
        return True

    # --- Phase 6: Support Tickets & Grounded Knowledge Base ---
    async def create_support_ticket(
        self,
        ticket_ref: str,
        customer_id: int,
        subject: str,
        description: str,
        priority: str = "MEDIUM"
    ) -> SupportTicket:
        ticket = SupportTicket(
            ticket_ref=ticket_ref,
            customer_id=customer_id,
            subject=subject,
            description=description,
            priority=priority,
            status="OPEN"
        )
        self.session.add(ticket)
        await self.session.flush()
        return ticket

    async def search_knowledge_docs(self, query_text: str, limit: int = 3) -> List[KnowledgeDoc]:
        words = [w for w in query_text.lower().split() if len(w) > 3]
        query = select(KnowledgeDoc)
        if words:
            from sqlalchemy import or_
            conditions = [KnowledgeDoc.title.ilike(f"%{w}%") for w in words] + [KnowledgeDoc.keywords.ilike(f"%{w}%") for w in words]
            query = query.where(or_(*conditions))
        query = query.limit(limit)
        result = await self.session.execute(query)
        return list(result.scalars().all())

    # --- Phase 7: Loans & Advisory Methods ---
    async def create_loan_application(
        self,
        application_ref: str,
        customer_id: int,
        loan_type: str,
        amount: float,
        tenure_months: int,
        interest_rate: float,
        monthly_emi: float,
        annual_income: float
    ) -> LoanApplication:
        app = LoanApplication(
            application_ref=application_ref,
            customer_id=customer_id,
            loan_type=loan_type,
            amount=amount,
            tenure_months=tenure_months,
            interest_rate=interest_rate,
            monthly_emi=monthly_emi,
            annual_income=annual_income,
            status="IN_REVIEW"
        )
        self.session.add(app)
        await self.session.flush()
        return app

    async def get_loan_applications(self, customer_id: int) -> List[LoanApplication]:
        query = select(LoanApplication).where(LoanApplication.customer_id == customer_id).order_by(LoanApplication.created_at.desc())
        result = await self.session.execute(query)
        return list(result.scalars().all())

    # --- Phase 7: Bill Payments & UPI ---
    async def get_billers(self, category: Optional[str] = None) -> List[Biller]:
        query = select(Biller)
        if category:
            query = query.where(Biller.category.ilike(category))
        result = await self.session.execute(query)
        return list(result.scalars().all())

    async def find_biller_by_name(self, name: str) -> Optional[Biller]:
        query = select(Biller).where(Biller.name.ilike(f"%{name}%"))
        result = await self.session.execute(query)
        return result.scalars().first()

    async def create_bill_payment(
        self,
        payment_ref: str,
        customer_id: int,
        biller_id: int,
        account_id: int,
        consumer_number: str,
        amount: float,
        idempotency_key: str
    ) -> BillPayment:
        payment = BillPayment(
            payment_ref=payment_ref,
            customer_id=customer_id,
            biller_id=biller_id,
            account_id=account_id,
            consumer_number=consumer_number,
            amount=amount,
            status="COMPLETED",
            idempotency_key=idempotency_key
        )
        self.session.add(payment)
        await self.session.flush()
        return payment

    async def get_bill_payments_by_customer(self, customer_id: int) -> List[BillPayment]:
        query = select(BillPayment).where(BillPayment.customer_id == customer_id).order_by(BillPayment.created_at.desc())
        result = await self.session.execute(query)
        return list(result.scalars().all())

    # --- ChatGPT-style Sessions & Message History ---
    async def get_or_create_session(
        self,
        thread_id: str,
        customer_id: int,
        title: str = "New Conversation"
    ) -> ChatSession:
        # thread_id is unique — look up by thread_id only to handle
        # guest-to-customer conversion (where customer_id changes mid-flow)
        query = select(ChatSession).where(ChatSession.thread_id == thread_id)
        result = await self.session.execute(query)
        session_obj = result.scalars().first()
        if session_obj:
            # Update customer_id if guest was converted to full customer
            if session_obj.customer_id != customer_id:
                session_obj.customer_id = customer_id
                await self.session.flush()
            return session_obj
        session_obj = ChatSession(
            thread_id=thread_id,
            customer_id=customer_id,
            title=title
        )
        self.session.add(session_obj)
        await self.session.flush()
        return session_obj

    async def update_session(self, thread_id: str, customer_id: int, title: Optional[str] = None):
        query = select(ChatSession).where(ChatSession.thread_id == thread_id, ChatSession.customer_id == customer_id)
        result = await self.session.execute(query)
        session_obj = result.scalars().first()
        if session_obj:
            if title and session_obj.title == "New Conversation":
                session_obj.title = title
            session_obj.updated_at = datetime.now(timezone.utc).replace(tzinfo=None)
            await self.session.flush()

    async def list_sessions_by_customer(self, customer_id: int) -> List[ChatSession]:
        query = select(ChatSession).where(ChatSession.customer_id == customer_id).order_by(ChatSession.updated_at.desc())
        result = await self.session.execute(query)
        return list(result.scalars().all())

    async def get_session(self, thread_id: str, customer_id: int) -> Optional[ChatSession]:
        query = select(ChatSession).where(ChatSession.thread_id == thread_id, ChatSession.customer_id == customer_id)
        result = await self.session.execute(query)
        return result.scalars().first()

    async def delete_session(self, thread_id: str, customer_id: int) -> bool:
        session_obj = await self.get_session(thread_id, customer_id)
        if not session_obj:
            return False

        # Delete messages associated with thread
        from sqlalchemy import delete
        await self.session.execute(delete(ChatMessage).where(ChatMessage.thread_id == thread_id, ChatMessage.customer_id == customer_id))
        await self.session.delete(session_obj)
        await self.session.flush()
        return True

    async def save_chat_message(
        self,
        thread_id: str,
        customer_id: int,
        role: str,
        content: str,
        active_workflow: str = "NONE",
        requires_action: Optional[str] = None,
        action_payload: Optional[dict] = None,
        widget_type: Optional[str] = None,
        widget_data: Optional[dict] = None
    ) -> ChatMessage:
        msg = ChatMessage(
            thread_id=thread_id,
            customer_id=customer_id,
            role=role,
            content=content,
            active_workflow=active_workflow,
            requires_action=requires_action,
            action_payload=action_payload,
            widget_type=widget_type,
            widget_data=widget_data
        )
        self.session.add(msg)
        await self.session.flush()
        return msg

    async def get_messages_by_thread(self, thread_id: str, customer_id: int) -> List[ChatMessage]:
        query = select(ChatMessage).where(
            ChatMessage.thread_id == thread_id,
            ChatMessage.customer_id == customer_id
        ).order_by(ChatMessage.created_at.asc())
        result = await self.session.execute(query)
        return list(result.scalars().all())

    async def update_customer_aadhaar_kyc(
        self,
        customer_id: int,
        aadhaar_masked: str,
        aadhaar_data: Optional[dict] = None
    ) -> Optional[Customer]:
        customer = await self.session.get(Customer, customer_id)
        if customer:
            customer.aadhaar_number_masked = aadhaar_masked
            customer.aadhaar_verified = True
            customer.aadhaar_data = aadhaar_data
            await self.session.flush()
        return customer

    async def update_customer_biometric_kyc(
        self,
        customer_id: int,
        selfie_url: str,
        face_match_score: float,
        liveness_verified: bool = True
    ) -> Optional[Customer]:
        customer = await self.session.get(Customer, customer_id)
        if customer:
            customer.live_selfie_url = selfie_url
            customer.face_match_score = face_match_score
            customer.liveness_verified = liveness_verified
            customer.kyc_mode = "DIGITAL_VIDEO_KYC"
            customer.kyc_status = "VERIFIED"
            await self.session.flush()
        return customer

    async def update_customer_business_gst(
        self,
        customer_id: int,
        company_name: str,
        business_type: str,
        gstin: str,
        gst_details: Optional[dict] = None
    ) -> Optional[Customer]:
        customer = await self.session.get(Customer, customer_id)
        if customer:
            customer.company_name = company_name
            customer.business_type = business_type
            customer.gstin = gstin
            customer.gst_verified = True
            customer.gst_details = gst_details
            await self.session.flush()
        return customer

    async def get_account_by_customer_and_type(
        self,
        customer_id: int,
        account_type: str
    ) -> Optional[Account]:
        query = select(Account).where(
            Account.customer_id == customer_id,
            Account.account_type == account_type.upper()
        )
        result = await self.session.execute(query)
        return result.scalars().first()


