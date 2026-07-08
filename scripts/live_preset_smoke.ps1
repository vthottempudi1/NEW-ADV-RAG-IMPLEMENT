param(
    [string]$ApiBase = "https://api.aiscientificlabs.com",
    [string]$Password = "Test123!"
)

$ErrorActionPreference = "Stop"

$username = "codex." + [guid]::NewGuid().ToString("N").Substring(0, 8) + "@example.com"
$registerBody = @{
    username = $username
    password = $Password
} | ConvertTo-Json -Compress

$register = Invoke-RestMethod `
    -Method Post `
    -Uri "$ApiBase/auth/register" `
    -ContentType "application/json" `
    -Body $registerBody

$headers = @{
    Authorization = "Bearer $($register.token)"
}

$presets = @(
    @{
        name = "Hybrid Default"
        question = "How many P1 incidents were resolved last quarter and what does our escalation policy say for P1 incidents?"
        search_mode = "hybrid"
        enable_rerank = $true
        enable_hyde = $false
        enable_crag = $true
        enable_self_reflective = $false
    },
    @{
        name = "RAG Policy"
        question = "What does our escalation policy say for P1 incidents?"
        search_mode = "hybrid"
        enable_rerank = $true
        enable_hyde = $false
        enable_crag = $true
        enable_self_reflective = $false
    },
    @{
        name = "SQL Count"
        question = "How many P1 incidents were resolved last quarter?"
        search_mode = "hybrid"
        enable_rerank = $true
        enable_hyde = $false
        enable_crag = $true
        enable_self_reflective = $false
    },
    @{
        name = "Troubleshooting"
        question = "What does ErrImagePull mean and how do I fix it?"
        search_mode = "hybrid"
        enable_rerank = $true
        enable_hyde = $false
        enable_crag = $true
        enable_self_reflective = $false
    },
    @{
        name = "HyDE Search"
        question = "How do I make sure my app keeps running even if a server dies?"
        search_mode = "hybrid"
        enable_rerank = $true
        enable_hyde = $true
        enable_crag = $false
        enable_self_reflective = $false
    },
    @{
        name = "SRAG Reflection"
        question = "My Kubernetes app keeps restarting, and I am not sure whether the root cause is the liveness probe, OOMKilled, or a bad image. How should I troubleshoot it step by step?"
        search_mode = "hybrid"
        enable_rerank = $true
        enable_hyde = $false
        enable_crag = $true
        enable_self_reflective = $true
    }
)

$results = @()
foreach ($preset in $presets) {
    $queryBody = @{
        question = $preset.question
        top_k = 5
        search_mode = $preset.search_mode
        enable_rerank = $preset.enable_rerank
        enable_hyde = $preset.enable_hyde
        enable_crag = $preset.enable_crag
        enable_self_reflective = $preset.enable_self_reflective
    } | ConvertTo-Json -Compress

    try {
        $queryResponse = Invoke-RestMethod `
            -Method Post `
            -Uri "$ApiBase/query" `
            -Headers $headers `
            -ContentType "application/json" `
            -Body $queryBody

        if ($queryResponse.pending_sql) {
            $approveBody = @{
                query_id = $queryResponse.pending_sql.query_id
                approved = $true
            } | ConvertTo-Json -Compress

            $approvedResponse = Invoke-RestMethod `
                -Method Post `
                -Uri "$ApiBase/query/sql/execute" `
                -Headers $headers `
                -ContentType "application/json" `
                -Body $approveBody

            $results += [pscustomobject]@{
                preset = $preset.name
                status = 200
                route = $approvedResponse.metadata.route
                pending_sql = $true
                answer_preview = $approvedResponse.answer.Substring(0, [Math]::Min(140, $approvedResponse.answer.Length))
            }
        }
        else {
            $results += [pscustomobject]@{
                preset = $preset.name
                status = 200
                route = $queryResponse.metadata.route
                pending_sql = $false
                answer_preview = $queryResponse.answer.Substring(0, [Math]::Min(140, $queryResponse.answer.Length))
            }
        }
    }
    catch {
        $statusCode = $_.Exception.Response.StatusCode.value__
        $raw = $_.ErrorDetails.Message
        $results += [pscustomobject]@{
            preset = $preset.name
            status = $statusCode
            route = "error"
            pending_sql = $false
            answer_preview = $raw.Substring(0, [Math]::Min(240, $raw.Length))
        }
    }
}

$badApprovalBody = @{
    query_id = "00000000-0000-0000-0000-000000000000"
    approved = $true
} | ConvertTo-Json -Compress

try {
    Invoke-RestMethod `
        -Method Post `
        -Uri "$ApiBase/query/sql/execute" `
        -Headers $headers `
        -ContentType "application/json" `
        -Body $badApprovalBody | Out-Null

    $badApproval = [pscustomobject]@{
        status = 200
        detail = "unexpected_success"
    }
}
catch {
    $badApproval = [pscustomobject]@{
        status = $_.Exception.Response.StatusCode.value__
        detail = $_.ErrorDetails.Message
    }
}

[pscustomobject]@{
    user = $username
    presets = $results
    stale_sql_approval = $badApproval
} | ConvertTo-Json -Depth 8
