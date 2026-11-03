STATUS=ERROR
sby -f test4.data_dn.sby > /dev/null && STATUS=$(awk '{print $1}' test4.data_dn/status)
echo $STATUS > status
case $STATUS in
    PASS)
        echo "Proved equivalence of partition 'test4.data_dn' using strategy 'pdr'"
    ;;
    FAIL)
        echo "Could not prove equivalence of partition 'test4.data_dn' using strategy 'pdr': partitions not equivalent"
    ;;
    UNKNOWN)
        echo "Could not prove equivalence of partition 'test4.data_dn' using strategy 'pdr': equivalence unknown"
    ;;
    TIMEOUT)
        echo "Could not prove equivalence of partition 'test4.data_dn' using strategy 'pdr': timeout"
    ;;
    *)
        cat test4.data_dn/ERROR 2> /dev/null
        echo "Execution of strategy 'pdr' on partition 'test4.data_dn' encountered an error."
        echo "More details can be found in '/home/yangsenyu/fpga-windows-native-v25-20261103/proof-shared-runtime-once/formal/test4/candidate/proof/strategies/test4.data_dn/pdr/test4.data_dn/logfile.txt'."
        exit 1
    ;;
esac
exit 0

