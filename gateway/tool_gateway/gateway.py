"""Central Tool Gateway enforcing RBAC, Idempotency, and Audit logging across all banking capabilities."""

from typing import Dict, Any, Optional
from database.repositories.banking_repo import BankingRepository
from gateway.tool_gateway.permissions import authorize_tool_execution
from gateway.tool_gateway.idempotency import idempotency_manager
from tools.base import ToolResult
from tools.accounts import get_balance, get_accounts
from tools.beneficiaries import get_beneficiary, list_beneficiaries, add_beneficiary
from tools.transfers import initiate_transfer
from tools.transactions import get_transaction, get_recent_transactions
from tools.cards import get_cards, freeze_card, unfreeze_card, replace_card, set_card_limits
from tools.loans import calculate_emi_tool, check_loan_eligibility_tool, apply_loan_tool, get_loan_status_tool
from tools.payments import get_billers_tool, fetch_bill_tool, pay_bill_tool, verify_upi_id_tool
from tools.knowledge import search_knowledge_base_tool, create_support_ticket_tool
from tools.insights import get_spending_insights_tool, detect_subscriptions_tool, predict_cashflow_tool
from tools.kyc import verify_aadhaar, verify_live_face_kyc, verify_gst
from tools.statements import generate_account_statement, explain_transaction
from tools.wealth import calculate_sip_tool, recommend_portfolio_tool, search_market_stocks_tool
from tools.policies import get_policy_details_tool, compare_policies_tool
from database.models.banking import Customer
import structlog

logger = structlog.get_logger(__name__)


class ToolGateway:
    async def execute_tool(
        self,
        agent_role: str,
        tool_name: str,
        repo: BankingRepository,
        customer_id: int,
        parameters: Dict[str, Any],
        thread_id: Optional[str] = None
    ) -> ToolResult:
        """
        Executes a banking tool under strict enterprise governance:
        1. Agent identity RBAC authorization
        2. Financial idempotency check (if applicable)
        3. Invocation of authorized capability
        4. Audit logging
        """
        # 1. Authorize agent identity
        authorize_tool_execution(agent_role, tool_name)

        # 2. Check idempotency for mutating financial operations
        idempotency_key = parameters.get("idempotency_key")
        if idempotency_key:
            cached = await idempotency_manager.get_result(idempotency_key)
            if cached and cached.get("status") == "COMPLETED":
                logger.info("Idempotent replay detected", tool=tool_name, idempotency_key=idempotency_key)
                return ToolResult(
                    success=True,
                    data=cached.get("result"),
                    idempotent_replay=True
                )

            acquired = await idempotency_manager.acquire_lock(idempotency_key)
            if not acquired:
                return ToolResult(
                    success=False,
                    error=f"Concurrent execution in progress for idempotency key '{idempotency_key}'."
                )

        # 3. Dispatch to concrete tool
        result: ToolResult
        try:
            # Accounts & Transfers
            if tool_name == "get_balance":
                result = await get_balance(
                    repo=repo,
                    customer_id=customer_id,
                    account_number=parameters.get("account_number")
                )
            elif tool_name == "get_accounts":
                result = await get_accounts(repo=repo, customer_id=customer_id)
            elif tool_name == "get_beneficiary":
                result = await get_beneficiary(
                    repo=repo,
                    customer_id=customer_id,
                    name=parameters["name"]
                )
            elif tool_name == "add_beneficiary":
                result = await add_beneficiary(
                    repo=repo,
                    customer_id=customer_id,
                    name=parameters["name"],
                    account_number=parameters["account_number"],
                    ifsc_code=parameters.get("ifsc_code", "NOVA0001001")
                )
            elif tool_name == "list_beneficiaries":
                result = await list_beneficiaries(repo=repo, customer_id=customer_id)
            elif tool_name == "initiate_transfer":
                result = await initiate_transfer(
                    repo=repo,
                    customer_id=customer_id,
                    source_account_id=parameters["source_account_id"],
                    beneficiary_id=parameters["beneficiary_id"],
                    amount=parameters["amount"],
                    idempotency_key=parameters["idempotency_key"],
                    fraud_score=parameters.get("fraud_score", 0.0)
                )
            elif tool_name == "get_transaction":
                result = await get_transaction(
                    repo=repo,
                    customer_id=customer_id,
                    transaction_ref=parameters["transaction_ref"]
                )
            elif tool_name == "get_recent_transactions":
                result = await get_recent_transactions(
                    repo=repo,
                    customer_id=customer_id,
                    limit=parameters.get("limit", 5)
                )

            # Phase 5: Cards
            elif tool_name == "get_cards":
                result = await get_cards(repo=repo, customer_id=customer_id)
            elif tool_name == "freeze_card":
                result = await freeze_card(repo=repo, customer_id=customer_id, card_type=parameters.get("card_type", "DEBIT"))
            elif tool_name == "unfreeze_card":
                result = await unfreeze_card(repo=repo, customer_id=customer_id, card_type=parameters.get("card_type", "DEBIT"))
            elif tool_name == "replace_card":
                result = await replace_card(
                    repo=repo,
                    customer_id=customer_id,
                    card_type=parameters.get("card_type", "DEBIT"),
                    reason=parameters.get("reason", "LOST")
                )
            elif tool_name == "set_card_limits":
                result = await set_card_limits(
                    repo=repo,
                    customer_id=customer_id,
                    card_type=parameters.get("card_type", "DEBIT"),
                    atm_limit=parameters.get("atm_limit"),
                    online_limit=parameters.get("online_limit")
                )

            # Phase 6: Knowledge & Support Tickets
            elif tool_name == "search_knowledge_base":
                result = await search_knowledge_base_tool(
                    repo=repo,
                    query=parameters.get("query", ""),
                    limit=parameters.get("limit", 3)
                )
            elif tool_name == "create_support_ticket":
                result = await create_support_ticket_tool(
                    repo=repo,
                    customer_id=customer_id,
                    subject=parameters["subject"],
                    description=parameters["description"],
                    priority=parameters.get("priority", "MEDIUM")
                )

            # Phase 7: Loans
            elif tool_name == "calculate_emi":
                result = await calculate_emi_tool(
                    principal=parameters["principal"],
                    tenure_months=parameters["tenure_months"],
                    annual_rate_pct=parameters.get("annual_rate_pct", 10.5)
                )
            elif tool_name == "check_loan_eligibility":
                result = await check_loan_eligibility_tool(
                    monthly_income=parameters["monthly_income"],
                    existing_emi=parameters.get("existing_emi", 0.0),
                    requested_amount=parameters["requested_amount"],
                    tenure_months=parameters["tenure_months"],
                    annual_rate_pct=parameters.get("annual_rate_pct", 10.5)
                )
            elif tool_name == "apply_loan":
                result = await apply_loan_tool(
                    repo=repo,
                    customer_id=customer_id,
                    loan_type=parameters.get("loan_type", "PERSONAL"),
                    amount=parameters["amount"],
                    tenure_months=parameters["tenure_months"],
                    annual_income=parameters["annual_income"],
                    annual_rate_pct=parameters.get("annual_rate_pct", 10.5)
                )
            elif tool_name == "get_loan_status":
                result = await get_loan_status_tool(repo=repo, customer_id=customer_id)

            # Phase 7: Bill Payments & UPI
            elif tool_name == "get_billers":
                result = await get_billers_tool(repo=repo, category=parameters.get("category"))
            elif tool_name == "fetch_bill":
                result = await fetch_bill_tool(
                    repo=repo,
                    biller_name=parameters["biller_name"],
                    consumer_number=parameters["consumer_number"]
                )
            elif tool_name == "pay_bill":
                result = await pay_bill_tool(
                    repo=repo,
                    customer_id=customer_id,
                    biller_name=parameters["biller_name"],
                    consumer_number=parameters["consumer_number"],
                    amount=parameters["amount"],
                    source_account_id=parameters["source_account_id"],
                    idempotency_key=parameters["idempotency_key"]
                )
            elif tool_name == "verify_upi_id":
                result = await verify_upi_id_tool(upi_id=parameters["upi_id"])

            # Next-Gen: PFM & Spending Insights
            elif tool_name == "get_spending_insights":
                result = await get_spending_insights_tool(
                    repo=repo,
                    customer_id=customer_id,
                    days=parameters.get("days", 30)
                )
            elif tool_name == "detect_subscriptions":
                result = await detect_subscriptions_tool(
                    repo=repo,
                    customer_id=customer_id
                )
            elif tool_name == "predict_cashflow":
                result = await predict_cashflow_tool(
                    repo=repo,
                    customer_id=customer_id,
                    proposed_debit=parameters.get("proposed_debit", 0.0)
                )

            # Institutional KYC Tools
            elif tool_name == "verify_aadhaar":
                result = await verify_aadhaar(
                    repo=repo,
                    customer_id=customer_id,
                    aadhaar_number=parameters["aadhaar_number"],
                    declared_name=parameters.get("declared_name", ""),
                    image_b64=parameters.get("image_b64")
                )
            elif tool_name == "verify_live_face_kyc":
                result = await verify_live_face_kyc(
                    repo=repo,
                    customer_id=customer_id,
                    selfie_b64=parameters["selfie_b64"],
                    aadhaar_b64=parameters.get("aadhaar_b64"),
                    ear_metrics=parameters.get("ear_metrics")
                )
            elif tool_name == "verify_gst":
                result = await verify_gst(
                    repo=repo,
                    customer_id=customer_id,
                    gstin=parameters["gstin"],
                    company_name=parameters["company_name"],
                    business_type=parameters.get("business_type", "Private Limited"),
                    certificate_b64=parameters.get("certificate_b64")
                )

            # Bank Account Statements & Transaction Explainer
            elif tool_name == "generate_account_statement":
                customer = await repo.session.get(Customer, customer_id)
                ext_id = customer.external_id if customer else f"CUST-{customer_id}"
                result = await generate_account_statement(
                    repo=repo,
                    customer_external_id=parameters.get("customer_external_id", ext_id),
                    period_type=parameters.get("period_type"),
                    account_number=parameters.get("account_number")
                )
            elif tool_name == "explain_transaction":
                customer = await repo.session.get(Customer, customer_id)
                ext_id = customer.external_id if customer else f"CUST-{customer_id}"
                result = await explain_transaction(
                    repo=repo,
                    customer_external_id=parameters.get("customer_external_id", ext_id),
                    transaction_ref=parameters.get("transaction_ref"),
                    query_type=parameters.get("query_type")
                )

            # Wealth Advisory & Free Market Tools
            elif tool_name == "calculate_sip":
                result = await calculate_sip_tool(
                    monthly_investment=parameters.get("monthly_investment", 500.0),
                    tenure_years=parameters.get("tenure_years", 5),
                    annual_expected_cagr=parameters.get("annual_expected_cagr", 12.0),
                    user_persona=parameters.get("user_persona", "STUDENT"),
                    risk_profile=parameters.get("risk_profile", "MODERATE")
                )
            elif tool_name == "recommend_portfolio":
                result = await recommend_portfolio_tool(
                    monthly_amount=parameters.get("monthly_amount", 1000.0),
                    user_persona=parameters.get("user_persona", "STUDENT"),
                    risk_profile=parameters.get("risk_profile", "MODERATE")
                )
            elif tool_name == "search_market_stocks":
                result = await search_market_stocks_tool(
                    query=parameters.get("query", "best stocks"),
                    symbol=parameters.get("symbol")
                )

            # Insurance & Banking Policy Tools
            elif tool_name == "get_policy_details":
                result = await get_policy_details_tool(
                    policy_id=parameters.get("policy_id"),
                    category=parameters.get("category"),
                    query=parameters.get("query")
                )
            elif tool_name == "compare_policies":
                result = await compare_policies_tool(
                    policy_a_id=parameters.get("policy_a_id", ""),
                    policy_b_id=parameters.get("policy_b_id", "")
                )

            else:
                result = ToolResult(success=False, error=f"Unknown tool: '{tool_name}'.")
        except Exception as exc:
            logger.error("Tool execution failed", tool=tool_name, error=str(exc))
            result = ToolResult(success=False, error=f"Internal tool execution error: {str(exc)}")

        # 4. Save idempotency result
        if idempotency_key and result.success and result.data:
            await idempotency_manager.set_result(idempotency_key, result.data)

        # 5. Audit log
        await repo.log_audit(
            event_type=f"TOOL_CALL_{tool_name.upper()}",
            agent_id=agent_role,
            customer_id=customer_id,
            thread_id=thread_id,
            payload={"parameters": parameters, "success": result.success}
        )

        # 6. Financial Cache Invalidation: Purge customer cache upon mutating transactions
        if result.success and tool_name in [
            "initiate_transfer", "pay_bill", "freeze_card", "unfreeze_card",
            "replace_card", "set_card_limits", "apply_loan", "create_account"
        ]:
            from services.cache.cache_engine import cache_engine
            await cache_engine.invalidate_customer_cache(customer_id)

        return result


tool_gateway = ToolGateway()
