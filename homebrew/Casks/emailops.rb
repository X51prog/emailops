cask "emailops" do
  version "0.6.16"
  sha256 "d3c069b3161df59c00b6b31152c3faec92d49804647a03b4983b824354cb8192"

  url "https://github.com/emailops/emailops/releases/download/v#{version}/EmailOps-macos.dmg"
  name "EmailOps"
  desc "Privacy-first, AI-native email client"
  homepage "https://github.com/emailops/emailops"

  livecheck do
    url :url
    strategy :github_latest
  end

  depends_on macos: ">= :monterey"

  app "EmailOps.app"

  zap trash: [
    "~/Library/Application Support/com.emailops.app",
    "~/Library/Caches/com.emailops.app",
    "~/Library/HTTPStorages/com.emailops.app",
    "~/Library/Preferences/com.emailops.app.plist",
    "~/Library/Saved Application State/com.emailops.app.savedState",
    "~/Library/WebKit/com.emailops.app",
  ]
end
