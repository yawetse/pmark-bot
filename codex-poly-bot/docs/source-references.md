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
