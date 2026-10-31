# Repair: the firewall lets the internet in

**Shown when** a default policy of the router's firewall for traffic from the internet is
*allow*: traffic that no rule matches then reaches the router itself, or the devices in your
network, over IPv4 or IPv6.

With IPv6 every device in your network has an address the internet can reach; the default policy
is what keeps them closed.

**What to do**

1. In SRM's firewall settings, set the default policies for traffic from the internet (to the
   router and to your network, IPv4 and IPv6) to deny.
2. Add a rule for each service that must be reachable, for the device and port it runs on.

The repair disappears at the next slow update (every 5 minutes by default) after no default policy
for traffic from the internet allows. Policies for traffic within your network are not checked.
