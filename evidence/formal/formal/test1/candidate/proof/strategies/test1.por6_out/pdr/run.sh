STATUS=ERROR
sby -f test1.por6_out.sby > /dev/null && STATUS=$(awk '{print $1}' test1.por6_out/status)
echo $STATUS > status
case $STATUS in
    PASS)
        echo "Proved equivalence of partition 'test1.por6_out' using strategy 'pdr'"
    ;;
    FAIL)
        echo "Could not prove equivalence of partition 'test1.por6_out' using strategy 'pdr': partitions not equivalent"
    ;;
    UNKNOWN)
        echo "Could not prove equivalence of partition 'test1.por6_out' using strategy 'pdr': equivalence unknown"
    ;;
    TIMEOUT)
        echo "Could not prove equivalence of partition 'test1.por6_out' using strategy 'pdr': timeout"
    ;;
    *)
        cat test1.por6_out/ERROR 2> /dev/null
        echo "Execution of strategy 'pdr' on partition 'test1.por6_out' encountered an error."
        echo "More details can be found in '/home/yangsenyu/fpga-windows-native-v25-20261103/proof-shared-runtime-once/formal/test1/candidate/proof/strategies/test1.por6_out/pdr/test1.por6_out/logfile.txt'."
        exit 1
    ;;
esac
exit 0

