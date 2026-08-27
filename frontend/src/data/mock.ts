/**
 * Canned content for `/#/states`, the interaction-states reference page.
 *
 * Not used by the product. Everything the app shows now comes from the backend
 * — conversations, suggestions and the document library were all mock data
 * once, and each was a small lie about what worked. This survives only because
 * the states page has to render an answer without a running server.
 */
import type { Source } from "@/types";

export const STREAMED_ANSWER: { content: string; sources: Source[] } = {
  content: `### Deposit account comparison

The four retail deposit products differ mainly in the minimum balance required to avoid the service charge, and in whether profit is credited at all [1].

| Account type | Minimum balance | Profit rate | Eligibility |
| --- | --- | --- | --- |
| Asaan Current | PKR 100 | Not applicable | CNIC holder, low-risk profile only |
| Basic Banking | Nil | Not applicable | Any resident individual |
| PLS Savings | PKR 5,000 | 11.00% p.a. | Any resident individual or sole proprietor |
| Freedom Savings | PKR 25,000 | 12.25% p.a. | Salary credit of PKR 50,000+ per month |
| Senior Citizen Savings | PKR 10,000 | 13.50% p.a. | Age 60 and above, CNIC verified |

Profit on savings products is calculated on the average balance held across the month, not the closing balance [2]:

\`\`\`text
monthly_profit = (sum_of_daily_balances / days_in_month)
               * (annual_rate / 12)
               * withholding_adjustment
\`\`\`

Asaan Current and Basic Banking accounts carry no profit entitlement, so no withholding applies to them [3]. Freedom Savings reverts to the PLS Savings rate for any month in which the qualifying salary credit is not received [1].`,
  sources: [
    {
      id: "t1",
      index: 1,
      title: "Retail Deposit Products SOP",
      section: "2.1 Product Matrix",
      page: 14,
      relevance: 0.95,
      // The corpus states no department, so the API returns "" and the panel
      // skips the row. Kept empty here so the reference matches the product.
      department: "",
      effectiveDate: "05 Jan 2025",
      version: "2025.1",
      contextBefore:
        "The Bank offers four principal retail deposit products, each with its own minimum balance and eligibility conditions.",
      excerpt:
        "Freedom Savings requires a maintained minimum balance of PKR 25,000 and a qualifying salary credit of PKR 50,000 or above per month. Where the qualifying credit is not received in a given month, the account shall accrue profit at the prevailing PLS Savings rate for that month.",
      contextAfter:
        "Reversion is automatic and does not require customer instruction or branch intervention.",
    },
    {
      id: "t2",
      index: 2,
      title: "Retail Deposit Products SOP",
      section: "3.4 Profit Calculation",
      page: 22,
      relevance: 0.9,
      // The corpus states no department, so the API returns "" and the panel
      // skips the row. Kept empty here so the reference matches the product.
      department: "",
      effectiveDate: "05 Jan 2025",
      version: "2025.1",
      contextBefore:
        "Profit on all profit-bearing deposit accounts is computed monthly and credited on the first working day of the following month.",
      excerpt:
        "Profit shall be calculated on the average balance maintained during the month, derived from the sum of daily closing balances divided by the number of days in that month. Closing balance alone shall not be used as the basis of calculation.",
      contextAfter:
        "Withholding tax is applied at the rate applicable to the customer's filer status at the time of credit.",
    },
    {
      id: "t3",
      index: 3,
      title: "Retail Deposit Products SOP",
      section: "3.7 Withholding",
      page: 26,
      relevance: 0.83,
      // The corpus states no department, so the API returns "" and the panel
      // skips the row. Kept empty here so the reference matches the product.
      department: "",
      effectiveDate: "05 Jan 2025",
      version: "2025.1",
      contextBefore:
        "Withholding obligations arise only where profit is actually credited to the account.",
      excerpt:
        "Current account products, including Asaan Current and Basic Banking, carry no profit entitlement. Accordingly, no withholding tax arises on these accounts irrespective of the balance maintained.",
      contextAfter:
        "Branches shall not apply withholding entries to non-profit-bearing accounts under any circumstance.",
    },
    {
      id: "t4",
      index: 4,
      title: "Branchless Banking Agents Policy",
      section: "5.2 Account Opening Limits",
      page: 19,
      relevance: 0.71,
      department: "Digital Banking",
      effectiveDate: "18 Sep 2024",
      version: "2024",
      contextBefore:
        "Agents are authorised to open a restricted subset of deposit products on the Bank's behalf.",
      excerpt:
        "Agents may open Asaan Current and Basic Banking accounts only. Profit-bearing products shall be opened at a branch following full customer due diligence.",
      contextAfter:
        "Agent-opened accounts remain subject to the same monitoring thresholds as branch-opened accounts.",
    },
  ],
};
