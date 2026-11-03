STATUS=ERROR
sby -f pmux_case04_feedback.data_out.10.sby > /dev/null && STATUS=$(awk '{print $1}' pmux_case04_feedback.data_out.10/status)
echo $STATUS > status
case $STATUS in
    PASS)
        echo "Proved equivalence of partition 'pmux_case04_feedback.data_out.10' using strategy 'pdr'"
    ;;
    FAIL)
        echo "Could not prove equivalence of partition 'pmux_case04_feedback.data_out.10' using strategy 'pdr': partitions not equivalent"
    ;;
    UNKNOWN)
        echo "Could not prove equivalence of partition 'pmux_case04_feedback.data_out.10' using strategy 'pdr': equivalence unknown"
    ;;
    TIMEOUT)
        echo "Could not prove equivalence of partition 'pmux_case04_feedback.data_out.10' using strategy 'pdr': timeout"
    ;;
    *)
        cat pmux_case04_feedback.data_out.10/ERROR 2> /dev/null
        echo "Execution of strategy 'pdr' on partition 'pmux_case04_feedback.data_out.10' encountered an error."
        echo "More details can be found in '/home/yangsenyu/fpga-windows-native-v25-20261103/proof-shared-runtime-once/formal/pmux_case04_feedback/candidate/proof/strategies/pmux_case04_feedback.data_out.10/pdr/pmux_case04_feedback.data_out.10/logfile.txt'."
        exit 1
    ;;
esac
exit 0

