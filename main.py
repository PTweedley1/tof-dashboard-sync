from sync import triple_whale, ga4, justuno, dashboard, registry


def run(name, fn):
    try:
        fn()
    except Exception as e:
        print(f"  ERROR in {name}: {e}")


def main():
    print("=== TOF Dashboard Sync ===\n")
    run("Triple Whale", triple_whale.sync)
    run("GA4", ga4.sync)
    # run("Shopify", shopify.sync)      # coming soon
    # run("Recharge", recharge.sync)    # coming soon
    run("Justuno", justuno.sync)
    run("Dashboard", dashboard.sync)
    run("Registry", registry.sync)
    print("\nDone.")


if __name__ == "__main__":
    main()
