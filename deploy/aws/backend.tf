# CI has to share one state file: with a local tfstate every workflow run would
# start from an empty state and build a second stack. Backend blocks cannot
# interpolate variables, so the identifiers are literal.
terraform {
  backend "s3" {
    bucket       = "repomate-tf-state-513594860857"
    key          = "ap-south-1/repomate.tfstate"
    region       = "ap-south-1"
    use_lockfile = true
    encrypt      = true
  }
}
