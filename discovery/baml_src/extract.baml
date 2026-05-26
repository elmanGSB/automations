// discovery/baml_src/extract.baml

function ExtractInterviewInsights(transcript: string, meeting_title: string?, meeting_date: string?) -> InterviewExtraction {
  client ClaudeLocal
  prompt #"
    You are a customer discovery analyst for a food distribution startup. You analyze
    interviews with DISTRIBUTORS (food distribution companies), RETAILERS (grocery stores,
    restaurants, convenience stores), SUPPLIERS (food manufacturers, farmers, processors),
    INDUSTRY EXPERTS (consultants, analysts, trade leaders), and COMPETITORS (other
    distribution or distribution-tech companies).

    We're building for food distributors. Each interviewee type reveals different angles:
    distributors show direct pain points, retailers/suppliers show what distributors
    need to do better, experts provide macro patterns, competitors reveal market gaps.

    {{ _.role("user") }}

    Analyze this interview and extract:

    1. **Summary**: 2-3 sentences — who is this person, what do they need, key takeaway

    2. **Interviewee classification**:
       - Type: distributor, retailer, supplier, industry_expert, or competitor
       - Product categories they deal with: perishable, frozen, liquor, nonperishable, meat, produce, dairy, specialty, full_line

    3. **Behavioral segment** (Stanford GSB framework — pick ONE):
       - extreme_user: power user of current distribution systems, pushes boundaries
       - solution_user: already built workarounds (spreadsheets, manual tracking)
       - solution_seeker: actively looking for better solutions, open to change
       - stuck_in_status_quo: knows problems exist, doesn't act
       - complainer: vocal about problems but resistant to change

    4. **Demographics & background**: Extract any info mentioned: years in business,
       location, company size, revenue, number of employees, trucks, stores, etc.

    5. **Insights**: Every distinct problem, need, observation, opportunity, or quote.
       - Be specific — "delivery windows vary by 8 hours" not "delivery is unreliable"
       - Categorize each: ordering, delivery, pricing, inventory, communication, quality, returns, payments, compliance, relationship
       - Assign subcategory slug (pick the closest):
           ordering→(manual-entry-causes-errors|missed-upsell-crosssell|customer-wont-place-digitally|no-order-status-after-placed)
           delivery→(late-or-missed-delivery|wrong-items-dropped|8-hour-delivery-window)
           pricing→(wrong-price-on-invoice|customer-doesnt-know-price-before-ordering|margin-shrinking-undetected|promo-roi-invisible|rebates-and-allowances-uncollected|losing-deals-on-price)
           inventory→(unexpected-stockouts|perishable-spoilage|cash-locked-in-overstock|stock-data-always-stale)
           communication→(order-changes-lost|whatsapp-as-system-of-record|no-escalation-path)
           quality→(product-damaged-on-arrival|same-quality-problems-repeat)
           returns→(credit-takes-weeks|return-pickup-no-show)
           payments→(invoice-dispute-delays-payment|net-60-cash-flow-crunch|overdue-ar-not-followed-up)
           compliance→(records-missing-at-audit|regulatory-complexity-overwhelm)
           relationship→(account-lost-when-rep-leaves|rep-only-reacts-never-alerts|service-failures-erode-trust|new-rep-takes-months-to-ramp)
       - Rate severity: critical (blocking their business), high (major friction), medium (annoying), low (minor)
       - verbatim_quote is REQUIRED — always include a direct quote from the transcript

    6. **Empathy map** (Stanford GSB — for THIS person):
       - THINKS: internal thoughts about their business, role, industry
       - FEELS: emotions about distribution, relationships, challenges
       - SAYS: direct quotes and common phrases they use
       - DOES: observable actions, workarounds, daily habits

    7. **Clusters** (Stanford GSB Organize & Cluster): 2-5 rows of:
       - User type (who), Need (what they need solved), Insight (why it matters), Memorable quote

    8. **Memorable quotes**: The 3-5 lines you'd put in a pitch deck

    {% if meeting_title %}Meeting: {{ meeting_title }}{% endif %}
    {% if meeting_date %}Date: {{ meeting_date }}{% endif %}

    TRANSCRIPT:
    ---
    {{ transcript }}
    ---

    {{ ctx.output_format }}
  "#
}
