STATUS=ERROR
sby -f test4.only_5b.sby > /dev/null && STATUS=$(awk '{print $1}' test4.only_5b/status)
echo $STATUS > status
case $STATUS in
    PASS)
        echo "Proved equivalence of partition 'test4.only_5b' using strategy 'pdr'"
    ;;
    FAIL)
        echo "Could not prove equivalence of partition 'test4.only_5b' using strategy 'pdr': partitions not equivalent"
    ;;
    UNKNOWN)
        echo "Could not prove equivalence of partition 'test4.only_5b' using strategy 'pdr': equivalence unknown"
    ;;
    TIMEOUT)
        echo "Could not prove equivalence of partition 'test4.only_5b' using strategy 'pdr': timeout"
    ;;
    *)
        cat test4.only_5b/ERROR 2> /dev/null
        echo "Execution of strategy 'pdr' on partition 'test4.only_5b' encountered an error."
        echo "More details can be found in '/home/yangsenyu/fpga-windows-native-v25-20261103/proof-shared-runtime-once/formal/test4/baseline/proof/strategies/test4.only_5b/pdr/test4.only_5b/logfile.txt'."
        exit 1
    ;;
esac
exit 0

