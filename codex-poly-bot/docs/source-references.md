# Source References

REQ: REQ-DEP-008, REQ-DEP-002, REQ-WAL-003, REQ-EXE-017

These references document the external APIs and deployment services used by the current implementation.

## LLM Providers

- OpenAI Responses API: https://platform.openai.com/docs/api-reference/responses
- Anthropic Messages API: https://docs.anthropic.com/en/api/messages

## Trading Venues

- Polymarket CLOB API documentation: https://docs.polymarket.com/developers/CLOB/trades/trades-data-api
- Polymarket Gamma API documentation: https://docs.polymarket.com/market-data/fetching-markets
- Polygon PoS RPC endpoints: https://docs.polygon.technology/pos/reference/rpc-endpoints
- Historical Polymarket reference only, no copied code: https://github.com/warproxxx/poly_data
- Alpaca Trading API documentation: https://docs.alpaca.markets/docs/trading-api
- Alpaca order creation and position-intent reference: https://docs.alpaca.markets/reference/postorder
- Alpaca account and trading-plan fields: https://docs.alpaca.markets/docs/account-plans
- Alpaca asset shortability and borrow-status reference: https://docs.alpaca.markets/reference/get-v2-assets-symbol-1
- Alpaca U.S. market clock: https://docs.alpaca.markets/us/reference/legacyclock
- Alpaca current open position by symbol: https://docs.alpaca.markets/us/reference/getopenposition-1
- Alpaca filtered open orders: https://docs.alpaca.markets/us/v1.1/reference/getallorders-1
- Alpaca latest quote for one stock: https://docs.alpaca.markets/us/reference/stocklatestquotesingle-1

## Historical Import License Decision

The Polymarket history importer in this repo is a clean-room implementation. The
GPL-3.0 `warproxxx/poly_data` project may be used only as a public data-flow
reference. Do not copy source code, derived implementation code, or GPL-licensed
files from that repository into this project without a separate license decision.

## AWS Deployment

- AWS CloudFormation User Guide: https://docs.aws.amazon.com/AWSCloudFormation/latest/UserGuide/Welcome.html
- Amazon ECS with AWS Fargate: https://docs.aws.amazon.com/AmazonECS/latest/developerguide/AWS_Fargate.html
- AWS Secrets Manager authentication and access control: https://docs.aws.amazon.com/secretsmanager/latest/userguide/auth-and-access.html
- AWS CloudFormation `AWS::SES::EmailIdentity`: https://docs.aws.amazon.com/AWSCloudFormation/latest/UserGuide/aws-resource-ses-emailidentity.html
