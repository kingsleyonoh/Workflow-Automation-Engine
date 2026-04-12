# GHCR Configuration
$GITHUB_USER = "kingsleyonoh"
$IMAGE_NAME = "workflow-engine"
$IMAGE_TAG = "latest"
$REGISTRY = "ghcr.io"

# Full image URI
$IMAGE_URI = "$REGISTRY/$GITHUB_USER/${IMAGE_NAME}:$IMAGE_TAG"

# Function to check command execution
function Check-LastCommand {
    param([string]$StepName)
    if ($LASTEXITCODE -ne 0) {
        Write-Host "ERROR: $StepName failed with exit code $LASTEXITCODE" -ForegroundColor Red
        exit 1
    }
}

Write-Host "Building Docker Image..." -ForegroundColor Cyan
Write-Host "Image: $IMAGE_URI" -ForegroundColor Yellow

# Build the Docker image
docker build -t $IMAGE_URI .
Check-LastCommand "Docker Build"

Write-Host "`nBuild successful! Pushing to GHCR..." -ForegroundColor Green

# Push to GHCR
docker push $IMAGE_URI
Check-LastCommand "Docker Push"

Write-Host "`nDone! Image pushed to $IMAGE_URI" -ForegroundColor Green
Write-Host "Watchtower will auto-pull on the VPS within 5 minutes." -ForegroundColor Cyan
