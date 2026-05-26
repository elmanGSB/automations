// discovery/baml_src/types.baml

// Food distribution domain categories
enum InsightCategory {
  Ordering       @alias("ordering")
  Delivery       @alias("delivery")
  Pricing        @alias("pricing")
  Inventory      @alias("inventory")
  Communication  @alias("communication")
  Quality        @alias("quality")
  Returns        @alias("returns")
  Payments       @alias("payments")
  Compliance     @alias("compliance")
  Relationship   @alias("relationship")
}

enum InsightSubcategory {
  // ordering (matches InsightCategory order)
  ManualEntryCausesErrors      @alias("manual-entry-causes-errors")
  MissedUpsellCrosssell        @alias("missed-upsell-crosssell")
  CustomerWontPlaceDigitally   @alias("customer-wont-place-digitally")
  NoOrderStatusAfterPlaced     @alias("no-order-status-after-placed")
  // delivery
  LateOrMissedDelivery    @alias("late-or-missed-delivery")
  WrongItemsDropped       @alias("wrong-items-dropped")
  EightHourDeliveryWindow @alias("8-hour-delivery-window")
  // pricing
  WrongPriceOnInvoice                     @alias("wrong-price-on-invoice")
  CustomerDoesntKnowPriceBeforeOrdering   @alias("customer-doesnt-know-price-before-ordering")
  MarginShrinkingUndetected               @alias("margin-shrinking-undetected")
  PromoRoiInvisible                       @alias("promo-roi-invisible")
  RebatesAndAllowancesUncollected         @alias("rebates-and-allowances-uncollected")
  LosingDealsOnPrice                      @alias("losing-deals-on-price")
  // inventory
  UnexpectedStockouts     @alias("unexpected-stockouts")
  PerishableSpoilage      @alias("perishable-spoilage")
  CashLockedInOverstock   @alias("cash-locked-in-overstock")
  StockDataAlwaysStale    @alias("stock-data-always-stale")
  // communication
  OrderChangesLost           @alias("order-changes-lost")
  WhatsappAsSystemOfRecord   @alias("whatsapp-as-system-of-record")
  NoEscalationPath           @alias("no-escalation-path")
  // quality
  ProductDamagedOnArrival    @alias("product-damaged-on-arrival")
  SameQualityProblemsRepeat  @alias("same-quality-problems-repeat")
  // returns
  CreditTakesWeeks     @alias("credit-takes-weeks")
  ReturnPickupNoShow   @alias("return-pickup-no-show")
  // payments
  InvoiceDisputeDelaysPayment  @alias("invoice-dispute-delays-payment")
  Net60CashFlowCrunch          @alias("net-60-cash-flow-crunch")
  OverdueArNotFollowedUp       @alias("overdue-ar-not-followed-up")
  // compliance
  RecordsMissingAtAudit          @alias("records-missing-at-audit")
  RegulatoryComplexityOverwhelm  @alias("regulatory-complexity-overwhelm")
  // relationship
  AccountLostWhenRepLeaves   @alias("account-lost-when-rep-leaves")
  RepOnlyReactsNeverAlerts   @alias("rep-only-reacts-never-alerts")
  ServiceFailuresErodeTrust  @alias("service-failures-erode-trust")
  NewRepTakesMonthsToRamp    @alias("new-rep-takes-months-to-ramp")
}

// Stanford GSB behavioral segmentation
enum BehavioralSegment {
  ExtremeUser       @alias("extreme_user") @description("Power user of current systems, pushes boundaries, deep opinions")
  SolutionUser      @alias("solution_user") @description("Already built workarounds — spreadsheets, manual tracking, custom tools")
  SolutionSeeker    @alias("solution_seeker") @description("Actively looking for better solutions, open to change, has budget")
  StuckInStatusQuo  @alias("stuck_in_status_quo") @description("Knows problems exist, doesn't act — 'it's always been this way'")
  Complainer        @alias("complainer") @description("Vocal about problems but resistant to change, blames others")
}

class InterviewInsight {
  type "problem" | "need" | "observation" | "opportunity" | "quote"
  content string @description("Clear, concise description in 1-2 sentences. Be specific — 'delivery windows vary by 8 hours' not 'delivery is unreliable'")
  category InsightCategory @description("Food distribution domain category")
  subcategory InsightSubcategory @description("Specific subcategory slug matching the category")
  severity "critical" | "high" | "medium" | "low"
  sentiment "positive" | "negative" | "neutral" | "mixed"
  verbatim_quote string @description("Exact words from the participant that support this insight")
}

// Stanford GSB Empathy Map — 4 quadrants
class EmpathyMap {
  thinks string[] @description("Internal thoughts: role concerns, industry worries, strategic questions")
  feels string[] @description("Emotions: frustration, anxiety, hope, loyalty, resentment")
  says string[] @description("Direct quotes and common phrases they use — what they tell others")
  does string[] @description("Observable actions: workarounds, habits, tools they use, daily routines")
}

// Stanford GSB Cluster Table row
class ClusterEntry {
  user_type string @description("Who: 'Small retailer (independent shop owner)', 'Supplier sales manager'")
  need string @description("What they need solved: 'Predictable delivery windows'")
  insight string @description("The aha — why this matters, what behavior it drives")
  memorable_quote string @description("Verbatim quote that captures this cluster")
  category InsightCategory
}

class InterviewExtraction {
  summary string @description("2-3 sentences: who is this person, what do they need, key takeaway")
  participant_role string?
  company_name string?
  interviewee_type "distributor" | "retailer" | "supplier" | "industry_expert" | "competitor"
  product_categories string[] @description("What products they deal with: perishable, frozen, liquor, nonperishable, meat, produce, dairy, specialty, full_line")
  behavioral_segment BehavioralSegment
  demographics string? @description("Background info mentioned in interview: years in business, location, company size, revenue, # employees, # trucks, etc.")
  insights InterviewInsight[] @description("All distinct insights. Aim for 5-15 per interview.")
  empathy_map EmpathyMap @description("Empathy map for THIS interviewee — will be accumulated across interviews for persona synthesis later")
  clusters ClusterEntry[] @description("2-5 User/Need/Insight/Quote clusters for the synthesis table")
  memorable_quotes string[] @description("Top 3-5 most impactful, quotable lines")
}
