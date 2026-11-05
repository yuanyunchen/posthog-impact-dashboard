# PostHog teams: products and members (full)

Source: posthog.com Strapi API `/api/teams` (populated profiles, fetched 2026-11-03) + posthog repo `products/*/product.yaml` owners (master, 2026-11-03).
`*` = team lead; `(@x)` = GitHub handle from the profile's own `github` field. on_site = listed on posthog.com/teams.

| team slug | name | on_site | GitHub team (guess = slug convention) | products/ dirs owned | members |
|---|---|---|---|---|---|
| agent-infrastructure | Agent Infrastructure | Y | team-agent-infrastructure | ai_gateway, tasks | Alessandro(@tatoalo), Charles*(@charlesvien), Brandon(@brandonleung), Jonathan(@jonathanlab) |
| ai-observability | AI Observability | Y | team-ai-observability | ai_observability, llm_analytics | Carlos(@carlos-marchal), Radu*(@Radu-Raicea), Marco(@mgancita), Bernat(@bernatixer), Juliana(@jumeyermattosarruda) |
| ai-research | AI Research | Y | ai-research | ai_training, ml_inference | Nicholas*, Robbie(@robbie-c), Marcus(@MarconLP), Alex(@sortafreel) |
| apm | APM | Y | team-apm | alerts, alerts_platform, apm, logs, metrics, tracing, uptime_monitoring | Frank*(@frankh), Jon, Abe(@abheek9), Daniel(@DanielVisca), Jimmy |
| billing | Billing | Y | team-billing | billing, billing_alerts | Pawel*(@pawel-cebula), Marce(@MarceColl), Roy, Alexander, Daniel |
| blitzscale | Blitzscale | Y | - | - | James*(@jamesefhawkins), Tim(@timgl), Charles(@charlescook-ph), Raquel(@raquelmsmith), Scott, Ben(@benjackwhite), Paul(@pauldambra), Ben, Matt |
| builder-relations | Builder Relations | Y | - | - | Daniel*(@Zaltsman), Kliment(@kliment-slice), Brittany(@brittanyjoiner15), Adlet(@adletsmykov) |
| clickhouse | ClickHouse | Y | clickhouse | live_debugger | Pawel(@orian), Rory*(@rorylshanks), Bryan, Tommy, Juho |
| client-libraries | Client Libraries | Y | - | - | Manoel*(@marandaneto), Ioannis(@ioannisj), Dustin(@dustinbyrne), Anna(@turnipdabeets) |
| cloud-foundations | Cloud Foundations | Y | - | - | Danel, Michael*, Daniel, Aly(@sinthetix), Adam(@adickinson72) |
| cloud-platform | Cloud Platform | Y | - | - | Sven*(@langesven), Stephen(@Z3r0Sum), Keelan |
| context-and-mcp | Context & MCP | Y | team-context-and-mcp | context_layer, mcp_store, skills, webmcp | Richard*(@richardsolomou), Adam(@adboio), Jake(@JakeRuth) |
| conversations | Conversations | Y | conversations | business_knowledge, conversations, surveys | Aleks*(@veryayskiy), Marco(@mgancita) |
| customer-analytics | Customer Analytics | Y | - | - | Arthur*(@arthurdedeus) |
| customer-success-eu | Customer Success EU | Y | - | - | Dana*, Christophe, Ben, Simon(@simfish85), Andre(@andre347), Ella, Carles, Sean, Steven |
| customer-success-na-north | Customer Success NA North | Y | - | - | Phil*, Kaya(@kmt901), Jake(@jakesciotto), Simon(@simfish85), Ryland(@rylandbowlescz), Evelynn, Nathan, Alexi |
| customer-success-na-west | Customer Success NA West | Y | - | - | Sean(@seanosh), Luke(@LukeBaber1836), Jack, Steven(@steventruong), Sebastian*, Chris |
| data-modeling | Data Modeling | Y | team-data-modeling | data_catalog, data_modeling, data_quality, endpoints, warehouse_suggestions | Jovan*, Anna(@annaszell), Thiago(@thiagosalvatore), Sinan |
| data-tools | Data Tools | Y | team-data-tools | business_intelligence, notebooks, streamlit_apps | Marius*(@mariusandra), Anna(@annaszell) |
| demand-gen | Demand Gen | Y | - | - | Brian*, Jonah, Joe(@joethreepwood) |
| developer-experience | Developer Experience | Y | team-devex | commands, engineering_analytics, review_hog, stamphog, visual_review | Julian*(@webjunkie), Georges-Antoine(@gantoine), Raúl(@rnegron) |
| developer-marketing | Developer Marketing | Y | - | - | Joe*(@joethreepwood), Sara(@SaraMiteva), Cleo(@cleo-pleurodon), Lizzie(@Lizzieepton), Juliana(@jumeyermattosarruda) |
| editorial | Editorial | Y | - | - | Ian*(@ivanagas), Natalia, Jina(@jina-yoon), Liam(@liamg-posthog), Dennis(@dennisivy), Andy(@andyvan-ph), Sara |
| error-tracking | Error Tracking | Y | team-error-tracking | error_tracking | Hugues*, Aleksander(@ablaszkiewicz), Cory(@fivestarspicy), James |
| experiments | Experiments | Y | team-experiments | experiments | Anders(@andehen), Rodrigo(@rodrigoi), Juraj*(@jurajmajerik), Marcel, Ruby |
| feature-flags | Feature Flags | Y | team-feature-flags | cohorts, early_access_features, feature_flags | Phil*(@haacked), Gustavo Henrique, Matheus(@matheus-vb), Patricio(@patricio-posthog), Ruby |
| finance | Finance | Y | - | - | Matt, Ahmed, Janani*(@jkposthog) |
| forward-deployed-engineering | Forward Deployed Engineering | Y | - | - | Joshua(@ordehi), Leonard, Jon*(@jkersu), Simon(@simfish85) |
| graphics | Graphics | Y | - | - | Daniel, Lottie*(@lottiecoxon), Heidi |
| growth | Growth | Y | team-growth | account_audits, demo, growth, legal_documents, webmcp, wizard | Rafael*(@rafaeelaudibert), Matt, Fernando(@fercgomes) |
| gtm-engineering | GTM Engineering | Y | - | - | Abhischek(@abhischekt), Ben* |
| ingestion | Ingestion | Y | team-ingestion | managed_migrations | Paweł*, Eli(@elireisman), Nick, José, Zachary, Jure |
| mcp-analytics | MCP Analytics | Y | mcp-analytics | mcp_analytics, mcp_registry | Lucas*(@lucasheriques), Georgis, Mike |
| mobile-app | Mobile App | Y | - | - | Chris* |
| onboarding | Onboarding | Y | - | - | Magda*, Daniel(@danieldanilov), Mark, Jordan(@jterry63), Simon(@simfish85) |
| people | People & Ops | Y | - | - | Kendal, Fraser*(@fraserhopper), Hector(@hector-r-759), Tara, Carol, Judy, Milagros |
| platform-features | Platform Features | Y | team-platform-features | access_control, approvals, authorization, cross_project_dashboards, links, notifications, platform_features, reminders, security | Yasen*, Alex, Reece(@ReeceJones) |
| platform-ux | Platform UX | Y | - | - | Adam*(@adamleithp), Lucas |
| product-analytics | Product Analytics | Y | team-product-analytics | actions, annotations, dashboards, event_definitions, exports, groups, persons, product_analytics, pulse, subscriptions | Thomas*(@thmsobrmlr), Sam(@sampennington), Mike, Daniel(@GeneralistDev), Matt(@mattpua) |
| product-led-sales-west | Product-Led Sales West | Y | - | - | Jon(@consultingsultan), Ryan(@ryanmccrary), Tyler*, Will(@willwearing), Sean, Sufiyan, Patrick |
| query-performance | Query Performance | Y | - | - | Vasco*(@vassiedk), Mike, Sandy, Andy(@andyzzhao), George(@georgemunyoro) |
| replay | Replay | Y | team-replay | replay, replay_vision | Tue*(@TueHaulund), Cory(@fivestarspicy), Kim, Hayne |
| revops | RevOps | N | - | - | Erika, Mine*, Matt |
| sales-cs | New Business Sales | Y | - | - | Seb, Alex*, Chris, Tomas, Lorena(@biolorena), Andreas, Melad, Joey, Christopher, Sachin |
| sales-product-led | Product-Led Sales East | Y | - | - | Landon*, Leon, Catherine, Leo(@leonhardprinz), Anna-Marie, Yasmin(@yasmin-xyz), Kristofer |
| security | Security | Y | - | - | Tom*(@Piccirello), Felipe(@feliperalmeida), Lukas |
| self-driving | Self-Driving | Y | team-self-driving | autoresearch, mobile, signals | Olly, Andy, Annika(@annikaschmid), Georgiy*(@skoob13), Mikayla(@mikaylathompson), Dylan(@dmarticus) |
| support | Support | Y | - | - | Steven(@slshults), Abigail*(@abigailbramble), Ben(@darkopia), Ben(@HaynesPostHog), Luke(@luke-belton), Christian(@clr182), Kyle(@kyleswank), Eleftheria, Christiaan, Phillip, Xander(@xljones), Chris, Alin-emanuel |
| surfaces | Surfaces | Y | team-surfaces | canvas, desktop, posthog_ai, slack_app, today | Peter*(@k11kirky), Annika(@annikaschmid), Cleo(@cleo-pleurodon), Shy(@puemos), Vojta(@VojtechBartos), Adam(@adamleithp) |
| talent | Talent | Y | - | - | Fraser(@fraserhopper), Coua*(@couaphang), Júlia(@juliaedo), Rune(@RunePHog), Mark(@Doobles-PostHog), Zbynek, Eliana  |
| warehouse | Warehouse | Y | team-managed-warehouse | data_tools, data_warehouse, managed_warehouse | Eric*(@EDsCODE), Anna(@annaszell), James(@fuziontech), Bill Guowei(@bill-ph), Jakob(@jghoman), Benjamin(@benben) |
| warehouse-sources | Warehouse Sources | Y | team-warehouse-sources | warehouse_sources, warehouse_sources_queue | Tom*(@Gilbert09), Estefania(@estefaniarabadan), Daniel, Anna(@annaszell) |
| web-analytics | Web Analytics | Y | team-web-analytics | aeo, core_events, customer_analytics, marketing_analytics, revenue_analytics, web_analytics | Lucas*(@lricoy), Javier, Jordan, Mike, Arthur(@arthurdedeus) |
| website | Website | Y | - | - | Eli*(@smallbrownbike), Ian(@ianmatson) |
| wizard-and-docs | Wizard & Docs | Y | - | - | Vincent(@gewenyu99), Sarah(@sarahxsanders), Edwin*(@edwinyjlim), John(@johncwaters) |
| workflows | Workflows | Y | team-workflows | cdp, messaging, workflows | Meikel*, Daniel(@dmarchuk), Harley, Michael(@silthus) |
| youtube | Video | Y | - | - | Andy(@andyvan-ph), Alex*, Jordo |

## product.yaml owners with no matching website team

- @adamleithp: field_notes
- @adboio: product_tours
- @fivestarspicy: user_interviews
- @ksvat: user_interviews
- @pauldambra: user_interviews
- batch-exports: batch_exports
- team-analytics-platform: analytics_platform
